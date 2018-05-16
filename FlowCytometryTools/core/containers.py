from __future__ import absolute_import

import collections
import inspect
import warnings
from itertools import cycle
from random import sample

import matplotlib
import numpy as np
from fcsparser import parse as parse_fcs
from pandas import DataFrame

import FlowCytometryTools.core.graph as graph
from FlowCytometryTools.core.bases import (Measurement, MeasurementCollection, OrderedCollection,
                                           queueable)
from FlowCytometryTools.core.common_doc import doc_replacer
from FlowCytometryTools.core.graph import plot_ndpanel
from FlowCytometryTools.core.transforms import Transformation
from FlowCytometryTools.core.utils import to_list


class FCMeasurement(Measurement):
    """
    A class for holding flow cytometry data from
    a single well or a single tube.
    """

    @property
    def channels(self):
        """ A DataFrame containing complete channel information """
        if self.meta is not None:
            return self.meta['_channels_']

    @property
    def channel_names(self):
        """ A tuple containing the channel names. """
        if self.meta is not None:
            return self.meta['_channel_names_']

    def read_data(self, **kwargs):
        '''
        Read the datafile specified in Sample.datafile and
        return the resulting object.
        Does NOT assign the data to self.data

        It's advised not to use this method, but instead to access
        the data through the FCMeasurement.data attribute.
        '''
        meta, data = parse_fcs(self.datafile, **kwargs)
        return data

    def read_meta(self, **kwargs):
        '''
        Read only the annotation of the FCS file (without reading DATA segment).

        It's advised not to use this method, but instead to access
        the meta data through the FCMeasurement.meta attribute.
        '''
        # TODO Try to rewrite the code to be more logical
        # The reason the equivalent statement is not in the read_data method
        # above is because self.readdata_kwargs are passed
        # as **kwargs to the read_data function.
        if 'channel_naming' in self.readdata_kwargs:
            kwargs['channel_naming'] = self.readdata_kwargs['channel_naming']
        meta = parse_fcs(self.datafile,
                         reformat_meta=True,
                         meta_data_only=True, **kwargs)
        return meta

    def get_meta_fields(self, fields, kwargs={}):
        '''
        Return a dictionary of metadata fields
        '''
        fields = to_list(fields)
        meta = self.get_meta()
        return {field: meta.get(field) for field in fields}

    def ID_from_data(self, ID_field='$SRC'):
        '''
        Returns the well ID from the src keyword in the FCS file. (e.g., A2)
        This keyword may not appear in FCS files generated by other machines,
        in which case this function will raise an exception.
        '''
        try:
            return self.get_meta_fields(ID_field)[ID_field]
        except KeyError:
            msg = "The keyword '{}' does not exist in the following FCS file: {}"
            msg = msg.format(ID_field, self.datafile)
            raise Exception(msg)

    @doc_replacer
    def plot(self, channel_names, kind='histogram',
             gates=None, gate_colors=None, gate_lw=1, **kwargs):
        """Plot the flow cytometry data associated with the sample on the current axis.

        To produce the plot, follow up with a call to matplotlib's show() function.

        Parameters
        ----------
        {graph_plotFCM_pars}
        {FCMeasurement_plot_pars}
        {common_plot_ax}
        gates : [None, Gate, list of Gate]
            Gate must be of type {_gate_available_classes}.
        gate_lw: float | iterable
            line width to use when drawing gates
            if float, uses the same line width for all gates
            if iterable, then cycles between the values
        kwargs : dict
            Additional keyword arguments to be passed to graph.plotFCM

        Returns
        -------
        None : if no data is present
        plot_output : output of plot command used to draw (e.g., output of hist)

        Examples
        --------
        >>> sample.plot('Y2-A', bins=100, alpha=0.7, color='green', normed=1) # 1d histogram
        >>> sample.plot(['B1-A', 'Y2-A'], cmap=cm.Oranges, colorbar=False) # 2d histogram
        """
        ax = kwargs.get('ax')

        channel_names = to_list(channel_names)
        gates = to_list(gates)

        plot_output = graph.plotFCM(self.data, channel_names, kind=kind, **kwargs)

        if gates is not None:
            if gate_colors is None:
                gate_colors = cycle(('b', 'g', 'r', 'm', 'c', 'y'))

            if not isinstance(gate_lw, collections.Iterable):
                gate_lw = [gate_lw]

            gate_lw = cycle(gate_lw)

            for (g, c, lw) in zip(gates, gate_colors, gate_lw):
                g.plot(ax=ax, ax_channels=channel_names, color=c, lw=lw)

        return plot_output

    def view(self, channel_names='auto',
             gates=None,
             diag_kw={}, offdiag_kw={},
             gate_colors=None, **kwargs):
        """
        Generates a matrix of subplots allowing for a quick way
        to examine how the sample looks in different channels.

        Parameters
        ----------
        channel_names : [list | 'auto']
            List of channel names to plot.
        offdiag_plot : ['histogram' | 'scatter']
            Specifies the type of plot for the off-diagonal elements.
        diag_kw : dict
            Not implemented

        Returns
        ------------

        axes references
        """
        if channel_names == 'auto':
            channel_names = list(self.channel_names)

        def plot_region(channels, **kwargs):
            if channels[0] == channels[1]:
                channels = channels[0]
            kind = 'histogram'

            self.plot(channels, kind=kind, gates=gates,
                      gate_colors=gate_colors, autolabel=False)

        channel_list = np.array(list(channel_names), dtype=object)
        channel_mat = [[(x, y) for x in channel_list] for y in channel_list]
        channel_mat = DataFrame(channel_mat, columns=channel_list, index=channel_list)
        kwargs.setdefault('wspace', 0.1)
        kwargs.setdefault('hspace', 0.1)
        return plot_ndpanel(channel_mat, plot_region, **kwargs)

    def view_interactively(self, backend='wx'):
        '''Loads the current sample in a graphical interface for drawing gates.

        Parameters
        ----------
        backend: 'auto' | 'wx' | 'webagg'
            Specifies which backend should be used to view the sample.
        '''
        if backend == 'auto':
            if matplotlib.__version__ >= '1.4.3':
                backend = 'WebAgg'
            else:
                backend = 'wx'

        if backend == 'wx':
            from FlowCytometryTools.gui.wx_backend import gui
        elif backend == 'webagg':
            from FlowCytometryTools.gui.webagg_backend import gui
        else:
            raise ValueError('No support for backend {}'.format(backend))

        gui.GUILauncher(measurement=self)

    @queueable
    @doc_replacer
    def transform(self, transform, direction='forward',
                  channels=None, return_all=True, auto_range=True,
                  use_spln=True, get_transformer=False, ID=None,
                  apply_now=True,
                  args=(), **kwargs):
        """
        Applies a transformation to the specified channels.

        The transformation parameters are shared between all transformed channels.
        If different parameters need to be applied to different channels,
        use several calls to `transform`.

        Parameters
        ----------
        {FCMeasurement_transform_pars}
        ID : hashable | None
            ID for the resulting collection. If None is passed, the original ID is used.

        Returns
        -------
        new : FCMeasurement
            New measurement containing the transformed data.
        transformer : Transformation
            The Transformation applied to the input measurement.
            Only returned if get_transformer=True.

        Examples
        --------
        {FCMeasurement_transform_examples}
        """
        # Create new measurement
        new = self.copy()
        data = new.data

        channels = to_list(channels)
        if channels is None:
            channels = data.columns
        ## create transformer
        if isinstance(transform, Transformation):
            transformer = transform
        else:
            if auto_range:  # determine transformation range
                if 'd' in kwargs:
                    warnings.warn(
                        'Encountered both auto_range=True and user-specified range value in '
                        'parameter d.\n Range value specified in parameter d is used.')
                else:
                    channel_meta = self.channels
                    # the -1 below because the channel numbers begin from 1 instead of 0
                    # (this is fragile code)
                    ranges = [float(r['$PnR']) for i, r in channel_meta.iterrows() if
                              self.channel_names[i - 1] in channels]
                    if not np.allclose(ranges, ranges[0]):
                        raise Exception("""Not all specified channels have the same data range,
                            therefore they cannot be transformed together.\n
                            HINT: Try transforming one channel at a time.
                            You'll need to provide the name of the channel in the transform.""")

                    if transform in {'hlog', 'tlog', 'hlog_inv', 'tlog_inv'}:
                        # Hacky fix to make sure that 'd' is provided only
                        # for hlog / tlog transformations
                        kwargs['d'] = np.log10(ranges[0])
            transformer = Transformation(transform, direction, args, **kwargs)
        ## create new data
        transformed = transformer(data[channels], use_spln)
        if return_all:
            new_data = data
        else:
            new_data = data.filter(channels)
        new_data[channels] = transformed
        ## update new Measurement
        new.data = new_data

        if ID is not None:
            new.ID = ID
        if get_transformer:
            return new, transformer
        else:
            return new

    @doc_replacer
    def subsample(self, key, order='random', auto_resize=False):
        """
        Allows arbitrary slicing (subsampling) of the data.

        Parameters
        ----------
        {FCMeasurement_subsample_parameters}

        Returns
        -------
        FCMeasurement
            Sample with subsampled data.
        """

        data = self.get_data()
        num_events = data.shape[0]

        if isinstance(key, float):
            if (key > 1.0) or (key < 0.0):
                raise ValueError('If float, key must be between 0.0 and 1.0')
            key = int(num_events * key)
        elif isinstance(key, tuple):
            all_float = all([isinstance(x, float) for x in key])
            if (len(key) > 2) or (not all_float):
                raise ValueError('Tuple must consist of two floats, each between 0.0 and 1.0')
            start = int(num_events * key[0])
            stop = int(num_events * key[1])
            key = slice(start, stop)  # Convert to a slice

        try:
            if isinstance(key, slice):
                if auto_resize:
                    stop = key.stop if key.stop < num_events else num_events
                    start = key.start if key.start < num_events else num_events
                    key = slice(start, stop, key.step)  # Generate new slice
                newdata = data.iloc[key]
            elif isinstance(key, int):
                if auto_resize:
                    if key > num_events:
                        key = num_events
                if key < 1:
                    # EDGE CAES: Must return an empty sample
                    order = 'start'
                if order == 'random':
                    newdata = data.loc[sample(list(data.index), key)]  # Use loc not iloc here!!
                elif order == 'start':
                    newdata = data.iloc[:key]
                elif order == 'end':
                    newdata = data.iloc[-key:]
                else:
                    raise ValueError("order must be in ('random', 'start', 'end')")
            else:
                raise TypeError("'key' must be of type int, float, tuple or slice.")
        except IndexError:
            print("If you're encountering an out-of-bounds error, "
                  "try to setting 'auto_resize' to True.")
            raise
        newsample = self.copy()
        newsample.set_data(data=newdata)
        return newsample

    @queueable
    @doc_replacer
    def gate(self, gate, apply_now=True):
        '''
        Apply given gate and return new gated sample (with assigned data).

        Parameters
        ----------
        gate : {_gate_available_classes}

        Returns
        -------

        FCMeasurement
            Sample with data that passes gates
        '''
        data = self.get_data()
        newdata = gate(data)
        newsample = self.copy()
        newsample.data = newdata
        return newsample

    @property
    def counts(self):
        """ Returns total number of events. """
        data = self.get_data()
        return data.shape[0]


class FCCollection(MeasurementCollection):
    '''
    A dict-like class for holding flow cytometry samples.
    '''
    _measurement_class = FCMeasurement

    @doc_replacer
    def transform(self, transform, direction='forward', share_transform=True,
                  channels=None, return_all=True, auto_range=True,
                  use_spln=True, get_transformer=False, ID=None,
                  apply_now=True,
                  args=(), **kwargs):
        '''
        Apply transform to each Measurement in the Collection.

        Return a new Collection with transformed data.

        {_containers_held_in_memory_warning}

        Parameters
        ----------
        {FCMeasurement_transform_pars}
        ID : hashable | None
            ID for the resulting collection. If None is passed, the original ID is used.

        Returns
        -------
        new : FCCollection
            New collection containing the transformed measurements.
        transformer : Transformation
            The Transformation applied to the measurements.
            Only returned if get_transformer=True & share_transform=True.

        Examples
        --------
        {FCMeasurement_transform_examples}
        '''
        new = self.copy()
        if share_transform:

            channel_meta = list(self.values())[0].channels
            channel_names = list(self.values())[0].channel_names
            if channels is None:
                channels = list(channel_names)
            else:
                channels = to_list(channels)
            ## create transformer
            if isinstance(transform, Transformation):
                transformer = transform
            else:
                if auto_range:  # determine transformation range
                    if 'd' in kwargs:
                        warnings.warn('Encountered both auto_range=True and user-specified range '
                                      'value in parameter d.\n '
                                      'Range value specified in parameter d is used.')
                    else:
                        # the -1 below because the channel numbers begin from 1 instead of 0 (this is fragile code)
                        ranges = [float(r['$PnR']) for i, r in channel_meta.iterrows() if
                                  channel_names[i - 1] in channels]

                        if not np.allclose(ranges, ranges[0]):
                            raise Exception('Not all specified channels have the same '
                                            'data range, therefore they cannot be '
                                            'transformed together.')

                        if transform in {'hlog', 'tlog', 'hlog_inv', 'tlog_inv'}:
                            # Hacky fix to make sure that 'd' is provided only
                            # for hlog / tlog transformations
                            kwargs['d'] = np.log10(ranges[0])
                transformer = Transformation(transform, direction, args, **kwargs)
                if use_spln:
                    xmax = self.apply(lambda x: x[channels].max().max(), applyto='data').max().max()
                    xmin = self.apply(lambda x: x[channels].min().min(), applyto='data').min().min()
                    transformer.set_spline(xmin, xmax)
            ## transform all measurements
            for k, v in new.items():
                new[k] = v.transform(transformer, channels=channels, return_all=return_all,
                                     use_spln=use_spln, apply_now=apply_now)
        else:
            for k, v in new.items():
                new[k] = v.transform(transform, direction=direction, channels=channels,
                                     return_all=return_all, auto_range=auto_range,
                                     get_transformer=False,
                                     use_spln=use_spln, apply_now=apply_now, args=args, **kwargs)
        if ID is not None:
            new.ID = ID
        if share_transform and get_transformer:
            return new, transformer
        else:
            return new

    @doc_replacer
    def gate(self, gate, ID=None, apply_now=True):
        '''
        Applies the gate to each Measurement in the Collection, returning a new Collection with gated data.

        {_containers_held_in_memory_warning}

        Parameters
        ----------
        gate : {_gate_available_classes}

        ID : [ str, numeric, None]
            New ID to be given to the output. If None, the ID of the current collection will be used.
        '''

        def func(well):
            return well.gate(gate, apply_now=apply_now)

        return self.apply(func, output_format='collection', ID=ID)

    @doc_replacer
    def subsample(self, key, order='random', auto_resize=False, ID=None):
        """
        Allows arbitrary slicing (subsampling) of the data.

        .. note::

            When using order='random', the sampling is random
            for each of the measurements in the collection.

        Parameters
        ----------
        {FCMeasurement_subsample_parameters}

        Returns
        -------
        FCCollection or a subclass
            new collection of subsampled event data.
        """

        def func(well):
            return well.subsample(key=key, order=order, auto_resize=auto_resize)

        return self.apply(func, output_format='collection', ID=ID)

    def counts(self, ids=None, setdata=False, output_format='DataFrame'):
        """
        Return the counts in each of the specified measurements.

        Parameters
        ----------
        ids : [hashable | iterable of hashables | None]
            Keys of measurements to get counts of.
            If None is given get counts of all measurements.
        setdata : bool
            Whether to set the data in the Measurement object.
            Used only if data is not already set.
        output_format : DataFrame | dict
            Specifies the output format for that data.

        Returns
        -------
        [DataFrame | Dictionary]
            Dictionary keys correspond to measurement keys.
        """
        return self.apply(lambda x: x.counts, ids=ids, setdata=setdata, output_format=output_format)


class FCOrderedCollection(OrderedCollection, FCCollection):
    '''
    A dict-like class for holding flow cytometry samples that are arranged in a matrix.
    '''

    @doc_replacer
    def plot(self, channel_names, kind='histogram',
             gates=None, gate_colors=None,
             ids=None, row_labels=None, col_labels=None,
             xlim='auto', ylim='auto',
             autolabel=True,
             **kwargs):
        """
        Produces a grid plot with each subplot corresponding to the data at the given position.

        Parameters
        ---------------
        {FCMeasurement_plot_pars}
        {graph_plotFCM_pars}
        {_graph_grid_layout}

        Returns
        -------
        {_graph_grid_layout_returns}

        Examples
        --------

        Below, plate is an instance of FCOrderedCollection

        >>> plate.plot(['SSC-A', 'FSC-A'], kind='histogram', autolabel=True)
        >>> plate.plot(['SSC-A', 'FSC-A'], xlim=(0, 10000))
        >>> plate.plot(['B1-A', 'Y2-A'], kind='scatter', color='red', s=1, alpha=0.3)
        >>> plate.plot(['B1-A', 'Y2-A'], bins=100, alpha=0.3)
        >>> plate.plot(['B1-A', 'Y2-A'], bins=[linspace(-1000, 10000, 100), linspace(-1000, 10000, 100)], alpha=0.3)

        .. note::

            For more details see documentation for FCMeasurement.plot
            **kwargs passes arguments to both grid_plot and to FCMeasurement.plot.
        """
        ##
        # Note
        # -------
        # The function assumes that grid_plot and FCMeasurement.plot use unique key words.
        # Any key word arguments that appear in both functions are passed only to grid_plot in the end.

        ##
        # Automatically figure out which of the kwargs should
        # be sent to grid_plot instead of two sample.plot
        # (May not be a robust solution, we'll see as the code evolves

        grid_arg_list = inspect.getargspec(OrderedCollection.grid_plot).args

        grid_plot_kwargs = {'ids': ids,
                            'row_labels': row_labels,
                            'col_labels': col_labels}

        for key, value in list(kwargs.items()):
            if key in grid_arg_list:
                kwargs.pop(key)
                grid_plot_kwargs[key] = value

        ##
        # Make sure channel names is a list to make the code simpler below
        channel_names = to_list(channel_names)

        ##
        # Determine data limits for binning
        #

        if kind == 'histogram':
            nbins = kwargs.get('bins', 200)

            if isinstance(nbins, int):
                min_list = []
                max_list = []
                for sample in self:
                    min_list.append(self[sample].data[channel_names].min().values)
                    max_list.append(self[sample].data[channel_names].max().values)

                min_list = list(zip(*min_list))
                max_list = list(zip(*max_list))

                bins = []

                for i, c in enumerate(channel_names):
                    min_v = min(min_list[i])
                    max_v = max(max_list[i])
                    bins.append(np.linspace(min_v, max_v, nbins))

                # Check if 1d
                if len(channel_names) == 1:
                    bins = bins[0]  # bins should be an ndarray, not a list of ndarrays

                kwargs['bins'] = bins

        ##########
        # Defining the plotting function that will be used.
        # At the moment grid_plot handles the labeling
        # (rather than sample.plot or the base function
        # in GoreUtilities.graph

        def plot_sample(sample, ax):
            return sample.plot(channel_names, ax=ax,
                               gates=gates, gate_colors=gate_colors,
                               colorbar=False,
                               kind=kind, autolabel=False, **kwargs)

        xlabel, ylabel = None, None

        if autolabel:
            cnames = to_list(channel_names)
            xlabel = cnames[0]
            if len(cnames) == 2:
                ylabel = cnames[1]

        return self.grid_plot(plot_sample, xlim=xlim, ylim=ylim,
                              xlabel=xlabel, ylabel=ylabel,
                              **grid_plot_kwargs)


FCPlate = FCOrderedCollection
