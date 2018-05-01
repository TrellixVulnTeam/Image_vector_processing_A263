#!/usr/bin/env python

"""
@author: Jordan Graesser
Date Created: 4/17/2015
"""

from __future__ import division, print_function
from future.utils import viewitems
from builtins import int

import os
import sys
import time
import argparse
from copy import copy
from operator import itemgetter
import psutil

from . import raster_tools, vector_tools, rad_calibration

# NumPy
try:
    import numpy as np
except ImportError:
    raise ImportError('NumPy must be installed')

# PyTables
try:

    import tables

    tables.parameters.MAX_NUMEXPR_THREADS = 8
    tables.parameters.MAX_BLOSC_THREADS = 8

except ImportError:
    raise ImportError('PyTables must be installed')


STORAGE_DICT = raster_tools.STORAGE_DICT
JD_DICT = rad_calibration.julian_day_dictionary()

tables.parameters.MAX_NUMEXPR_THREADS = 4
tables.parameters.MAX_BLOSC_THREADS = 4


class OrderInfo(tables.IsDescription):

    index = tables.UInt32Col()
    jd = tables.UInt16Col()
    jdr = tables.UInt32Col()
    year = tables.UInt16Col()


class SensorInfo(tables.IsDescription):

    """Table columns"""

    Id = tables.StringCol(100)
    filename = tables.StringCol(100)
    storage = tables.StringCol(10)
    left = tables.Float64Col()
    top = tables.Float64Col()
    right = tables.Float64Col()
    bottom = tables.Float64Col()
    cell_size = tables.Float32Col()
    rows = tables.UInt16Col()
    rows_r = tables.UInt16Col()
    columns = tables.UInt16Col()
    columns_r = tables.UInt16Col()
    jd = tables.UInt16Col()
    jdr = tables.UInt32Col()
    utm = tables.UInt8Col()
    latitude = tables.StringCol(2)
    grid = tables.StringCol(2)
    bands = tables.UInt16Col()
    projection = tables.StringCol(1000)
    attribute = tables.StringCol(30)
    sensor = tables.StringCol(20)
    real_sensor = tables.StringCol(20)
    satellite = tables.StringCol(10)
    year = tables.UInt16Col()
    date = tables.StringCol(10)
    clear = tables.Float32Col()
    cblue = tables.UInt8Col()
    blue = tables.UInt8Col()
    green = tables.UInt8Col()
    red = tables.UInt8Col()
    nir = tables.UInt8Col()
    midir = tables.UInt8Col()
    farir = tables.UInt8Col()
    rededge = tables.UInt8Col()
    rededge2 = tables.UInt8Col()
    rededge3 = tables.UInt8Col()
    niredge = tables.UInt8Col()
    wv = tables.UInt8Col()              # Sentinel-2 water vapor band
    cirrus = tables.UInt8Col()
    zenith_angle = tables.Float64Col()
    azimuth_angle = tables.Float64Col()


class SetFilter(object):

    def set_filter(self, image_extension, **kwargs):

        """
        Sets the array storage filter

        Args:
            image_extension (str)
        """

        self.filters = tables.Filters(**kwargs)

        self.atom = tables.Atom.from_dtype(np.dtype(STORAGE_DICT[image_extension]))


def get_mem():

    """Gets the resident set size (MB) for the current process"""

    this_proc = psutil.Process(os.getpid())

    return this_proc.get_memory_info()[0] / 1E6


class BaseHandler(SetFilter):

    def add_array(self,
                  image_array=None,
                  array_storage=None,
                  image_shape=None,
                  array_type='c',
                  cloud_band_included=False,
                  **kwargs):

        """
        Adds an image array to the HDF file

        Args:
            image_array (Optional[ndarray]): A ndarray. Default is None.
            array_storage (Optional[str]):
            image_shape (Optional[tuple]):
            array_type (Optional[str]): Choices are ['a', 'c', 'e'].
            cloud_band_included (Optional[bool])
            kwargs (Optional): Parameters for the Atom filter.
        """

        if not array_storage:
            array_storage = self.image_info.storage.lower()

        if not image_shape:

            if self.image_info.bands > 1:

                if cloud_band_included:
                    n_bands = self.image_info.bands - 1
                else:
                    n_bands = self.image_info.bands

                image_shape = (n_bands,
                               self.image_info.rows,
                               self.image_info.cols)

            else:

                image_shape = (self.image_info.rows,
                               self.image_info.cols)

        # Set the atom filter
        self.set_filter(array_storage, **kwargs)

        if array_type == 'a':

            self.h5_file.create_array(self.node_name,
                                      self.name_dict['filename'],
                                      obj=self.image_info.read(bands2open=1),
                                      atom=self.atom,
                                      shape=image_shape,
                                      title=self.name_dict['attribute'])

        elif array_type == 'c':

            array = self.h5_file.create_carray(self.node_name,
                                               self.name_dict['filename'],
                                               atom=self.atom,
                                               shape=image_shape,
                                               filters=self.filters,
                                               title=self.name_dict['attribute'])

        elif array_type == 'e':

            self.h5_file.create_earray(self.node_name,
                                       self.name_dict['filename'],
                                       atom=self.atom,
                                       shape=(self.image_info.rows, 0),
                                       expectedrows=self.image_info.rows,
                                       filters=self.filters,
                                       title=self.name_dict['attribute'],
                                       obj=self.image_info.read(bands2open=1))

        if array_type != 'a':

            if array_type == 'e':
                array.append(image_array)
            else:

                # Enter the data into the carray.
                if isinstance(image_array, np.ndarray):

                    if len(image_array.shape) > 2:

                        for bi, band in enumerate(image_array):
                            array[bi] = band

                    else:
                        array[:] = image_array

                else:

                    if self.image_info.bands > 1:

                        if cloud_band_included:
                            bands2open = range(1, self.image_info.bands)
                        else:
                            bands2open = -1

                        for bi, band in enumerate(self.image_info.read(bands2open=bands2open)):
                            array[bi] = band

                    else:
                        array[:] = self.image_info.read(bands2open=1)

        self.close_image()

    def update_array(self, image2enter):

        if '_mask' in self.image_node:
            d_type = 'byte'
        else:
            d_type = 'float32'

        existing_array = self.get_array(self.image_node)

        array2enter_info = raster_tools.ropen(image2enter)
        array2enter = array2enter_info.read(bands2open=1, d_type=d_type)

        if '_mask' in self.image_node:

            iarg, jarg = np.where(((existing_array == 255) & (array2enter > 0) & (array2enter < 255)) |
                                  ((existing_array == 0) & (array2enter > 0) & (array2enter < 255)))

        else:
            iarg, jarg = np.where((existing_array == 0) & (array2enter != 0))

        existing_array[iarg, jarg] = array2enter[iarg, jarg]

        array2enter_info.close()

        # import matplotlib.pyplot as plt
        #
        # plt.subplot(121)
        # plt.imshow(existing_array)
        # plt.subplot(122)
        # plt.imshow(array2enter)
        # plt.show()
        # sys.exit()

    def get_array(self,
                  array_name,
                  z=None,
                  i=None,
                  j=None,
                  rows=None,
                  cols=None,
                  x=None,
                  y=None,
                  maximum=False,
                  info_dict=None,
                  time_formatted=False,
                  start_date=None,
                  end_date=None):

        """
        Gets a ndarray

        Args:
            array_name (str): The node name of the array to get.
            z (int): The starting band position.
            i (int): The starting row position.
            j (int): The starting column position.
            rows (int): The number of rows to get.
            cols (int): The number of columns to get.
            x (float): The x coordinate to index.
            y (float): The y coordinate to index.
            info_dict (Optional[dict])
            time_formatted (Optional[bool])
            start_date (Optional[str]): yyyy/mm/dd
            end_date (Optional[str]): yyyy/mm/dd
            maximum (Optional[bool]): Whether to return the array maximum instead of the array. Default is False.

        Returns:
            A ``rows`` x ``cols`` ndarray.

        Examples:
            >>> from mappy.utilities.landsat.pytables import manage_pytables
            >>>
            >>> pt = manage_pytables()
            >>> pt.open_hdf_file('/2000_p228.h5', mode='r')
            >>>
            >>> # open a 100 x 100 array
            >>> pt.get_array('/2000/p228r83/ETM/p228r83_etm_2000_0124_tcap_wetness', 0, 0, 100, 100)
        """

        self.z = z
        self.i = i
        self.j = j
        self.x = x
        self.y = y
        self.info_dict = info_dict
        self.start_date = start_date
        self.end_date = end_date

        if (isinstance(self.x, float) and isinstance(self.y, float)) or \
                (isinstance(self.x, list) and isinstance(self.y, list) and isinstance(self.x[0], float)):
            self._get_offsets()

        if isinstance(self.start_date, str):
            self.get_time_range()

        # names = [x['Id'] for x in table.where("""(attribute == "ndvi") & (path == 228) & (row == 83)""")]
        # names = [x['Id'] for x in table.where("""(path == 228) & (row == 83)""")]

        if maximum:

            try:
                return self.h5_file.get_node(array_name).read()[i:i+rows, j:j+cols].max()
            except NameError:
                raise NameError('\nThe array does not exist.\n')

        else:

            try:

                if time_formatted:

                    h5_node = self.h5_file.get_node(array_name).read()

                    if isinstance(self.i, int) and not isinstance(rows, int):

                        return self.h5_file.get_node(array_name).read()[self.i,
                               self.index_positions[0]:self.index_positions[-1]]

                    elif (isinstance(self.y, float) and not isinstance(rows, int)) or \
                            (isinstance(self.y, list) and isinstance(self.y[0], float) and not isinstance(rows, int)):

                        if isinstance(self.x, list):
                            self.i_ = [(i_ * self.info_dict['columns_r']) + j_ for i_, j_ in zip(self.i_, self.j_)]
                            return np.array([h5_node[i, self.index_positions[0]:self.index_positions[-1]+1]
                                             for i in self.i_], dtype='float32')
                        else:
                            self.i_ = (self.i_ * self.info_dict['columns_r']) + self.j_
                            return h5_node[self.i_, self.index_positions[0]:self.index_positions[-1]+1]

                    elif isinstance(self.i, int) and isinstance(rows, int):

                        return self.h5_file.get_node(array_name).read()[self.i:self.i+rows,
                               self.index_positions[0]:self.index_positions[-1]]

                    elif isinstance(self.y, float) and isinstance(rows, int):

                        self.i_ = (self.i_ * self.info_dict['columns_r']) + self.j_

                        return self.h5_file.get_node(array_name).read()[self.i_:self.i_+rows,
                               self.index_positions[0]:self.index_positions[-1]]

                else:

                    if isinstance(self.z, int) or isinstance(self.z, list):

                        if self.z == -1:
                            return self.h5_file.get_node(array_name).read()[:, self.i:self.i+rows, self.j:self.j+cols]
                        else:

                            return self.h5_file.get_node(array_name).read()[self.z,
                                                                            self.i:self.i+rows,
                                                                            self.j:self.j+cols]

                    else:

                        return self.h5_file.get_node(array_name).read()[self.i:self.i+rows,
                                                                        self.j:self.j+cols]

            except NameError:
                raise NameError('\nThe array does not exist.\n')

    def _get_offsets(self):

        image_list = [self.info_dict['left'], self.info_dict['top'],
                      self.info_dict['right'], self.info_dict['bottom'],
                      -self.info_dict['cell_size'], self.info_dict['cell_size']]

        if isinstance(self.x, list):

            self.i_ = []
            self.j_ = []

            for xs, ys in zip(self.x, self.y):

                __, __, j_, i_ = vector_tools.get_xy_offsets(image_list=image_list,
                                                             x=xs,
                                                             y=ys,
                                                             check_position=False)

                self.i_.append(i_)
                self.j_.append(j_)

        else:

            __, __, self.j_, self.i_ = vector_tools.get_xy_offsets(image_list=image_list,
                                                                   x=self.x,
                                                                   y=self.y,
                                                                   check_position=False)

    def get_time_range(self):

        sds = self.start_date.split('/')
        jds = rad_calibration.date2julian(sds[1], sds[2], sds[0])

        if isinstance(self.end_date, str):

            sde = self.end_date.split('/')
            jde = rad_calibration.date2julian(sde[1], sde[2], sde[0])

            query = """(jdr >= {:d}) & (jdr <= {:d})""".format(JD_DICT['{}-{:03d}'.format(sds[0], jds)],
                                                               JD_DICT['{}-{:03d}'.format(sde[0], jde)])

        else:
            query = """(jdr >= {:d})""".format(JD_DICT['{}-{:03d}'.format(sds[0], jds)])

        ot = self.h5_file.root.order

        self.column_index_a = [x['jdr'] for x in ot.where("""(jdr > 0)""")]
        self.column_index = [dict(jd=x['jd'], jdr=x['jdr']) for x in ot.where(query)]

        sti = self.column_index_a.index(self.column_index[0]['jdr'])
        ste = self.column_index_a.index(self.column_index[-1]['jdr'])

        # Sort on standardized Julian Days
        self.column_index = sorted(self.column_index, key=itemgetter('jdr'))

        self.index_positions = range(sti, ste+1)

        self.jd_index = [el['jd'] for el in self.column_index]
        self.jdr_index = [el['jdr'] for el in self.column_index]

        self.jd_index = list(np.unique(self.jd_index))
        self.jdr_index = list(np.unique(self.jdr_index))


class ArrayHandler(object):

    """
    A class to handle PyTables Arrays

    Examples:
        >>> from mappy.utilities.pytables import ArrayHandler
        >>>
        >>> a = np.random.random((100, 100, 100)).astype(np.float32)
        >>>
        >>> with ArrayHandler('/some_file.h5') as ea:
        >>>     ea.create_array(a.shape)
        >>>
        >>> with ArrayHandler('/some_file.h5') as ea:
        >>>     ea.add_array(a)
    """

    def __init__(self,
                 h5_file,
                 array_type='c',
                 complib='blosc',
                 complevel=5,
                 shuffle=True,
                 dtype='float32',
                 group_name=None,
                 group_title=None):

        self.h5_file = h5_file
        self.array_type = array_type
        self.dtype = dtype
        self.group_name = group_name
        self.group_title = '' if not group_title else group_title

        if os.path.isfile(self.h5_file):
            self.file_mode = 'a'
        else:
            self.file_mode = 'w'

        self._set_filter(complib=complib, complevel=complevel, shuffle=shuffle)

        # Open the HDF5 file.
        self._open_file()

        # Open the metadata table.
        self._open_table()

    def _open_table(self):

        # Get the nodes
        self.nodes = [node._v_title for node in self.h5_file.walk_nodes()]

        if 'metadata' in self.nodes:

            self.h5_table = self.h5_file.root.metadata
            self.column_names = self.h5_table.colnames

    def _open_file(self):
        self.h5_file = tables.open_file(self.h5_file, mode=self.file_mode)

    def evaluate(self, expression, **kwargs):

        """Evaluates an expression"""

        texpr = tables.Expr(expression, **kwargs)

        return texpr.eval()

    def create_array(self, array_shape, data_name=None):

        if not isinstance(data_name, str):
            data_name = 'data'

        if isinstance(self.group_name, str):

            # Check if the group exists.
            if not [True for node in self.h5_file.walk_nodes() if node._v_pathname == '/{}'.format(self.group_name)]:
                self.h5_file.create_group('/', self.group_name)

        # self.h5_file.create_carray(self.node_name, self.name_dict['filename'],
        #                            atom=self.atom,
        #                            shape=(self.image_info.rows, self.image_info.cols),
        #                            filters=self.filters,
        #                            title=self.name_dict['attribute'],
        #                            obj=self.image_info.read(bands2open=1))

        if self.array_type == 'c':

            if isinstance(self.group_name, str):

                self.data_storage = self.h5_file.create_carray('/{}'.format(self.group_name),
                                                               data_name,
                                                               atom=self.atom,
                                                               shape=array_shape,
                                                               filters=self.filters,
                                                               title=self.group_title)

            else:

                self.data_storage = self.h5_file.create_carray(self.h5_file.root,
                                                               data_name,
                                                               atom=self.atom,
                                                               shape=array_shape,
                                                               filters=self.filters,
                                                               title=self.group_title)

        elif self.array_type == 'e':

            if isinstance(self.group_name, str):

                self.data_storage = self.h5_file.create_earray('/{}'.format(self.group_name),
                                                               data_name,
                                                               atom=self.atom,
                                                               shape=array_shape,
                                                               filters=self.filters,
                                                               title=self.group_title)

            else:

                self.data_storage = self.h5_file.create_earray(self.h5_file.root,
                                                               data_name,
                                                               atom=self.atom,
                                                               shape=array_shape,
                                                               filters=self.filters,
                                                               title=self.group_title)

    def add_array(self, array2add, z=None, i=None, j=None, nz=None, nr=None, nc=None):

        if self.array_type == 'e':

            if isinstance(self.group_name, str):
                self.h5_file.get_node('/{}/data'.format(self.group_name)).append(array2add)
            else:
                self.h5_file.root.data.append(array2add)

        else:

            if not isinstance(z, int) and not isinstance(i, int):

                if isinstance(self.group_name, str):
                    self.data_storage[:] = array2add
                else:
                    self.h5_file.root.data[:] = array2add

            else:

                if isinstance(self.group_name, str):

                    if isinstance(z, int):
                        self.data_storage[z:z+nz, i:i+nr, j:j+nc] = array2add
                    else:
                        self.data_storage[i:i+nr, j:j+nc] = array2add

                else:

                    if isinstance(z, int):
                        self.h5_file.root.data[z:z+nz, i:i+nr, j:j+nc] = array2add
                    else:
                        self.h5_file.root.data[i:i+nr, j:j+nc] = array2add

    def read_array(self,
                   is_3d=False,
                   z=None,
                   i=None,
                   j=None,
                   nz=None,
                   nr=None,
                   nc=None,
                   is_flat=False,
                   d_type='float32'):

        """
        Reads an array from a HDF file

        Args:
            is_3d (Optional[bool]): Whether the array is 3-dimensional.
            z (Optional[int]): The starting index in the 3rd dimension.
            i (Optional[int or 1d array-like]): The starting row index.
            j (Optional[int or 1d array-like]): The starting column index.
            nz (Optional[int]): The number of dimensions to read along the 3rd dimension.
            nr (Optional[int]): The number of rows to read.
            nc (Optional[int]): The number of columns to read.
            is_flat (Optional[bool]): Whether the array is flat, or 1d-like.
            d_type (Optional[str]): The data type.
        """

        dtype_dict = dict(uint8=np.uint8,
                          uint16=np.uint16,
                          float32=np.float32,
                          float64=np.float64)

        dtype_func = dtype_dict[d_type]

        if is_3d:

            if isinstance(self.group_name, str):

                if not isinstance(z, int):
                    return self.h5_file.get_node(self.group_name)[:].astype(d_type)
                else:
                    return self.h5_file.get_node(self.group_name)[z:z+nz, i:i+nr, j:j+nc].astype(d_type)

            else:

                if not isinstance(z, int):
                    return self.h5_file.root.data[:].astype(d_type)
                else:
                    return self.h5_file.root.data[z:z+nz, i:i+nr, j:j+nc].astype(d_type)

        else:

            if isinstance(self.group_name, str):

                if is_flat:
                    return dtype_func(self.h5_file.get_node(self.group_name)[i])
                else:

                    if (i is None) and (j is None):
                        return dtype_func(self.h5_file.get_node(self.group_name)[:])
                    else:

                        if isinstance(i, np.ndarray):

                            if isinstance(j, np.ndarray) or isinstance(j, int):
                                return dtype_func(self.h5_file.get_node(self.group_name)[i, j])
                            else:
                                return dtype_func(self.h5_file.get_node(self.group_name)[i, :])

                        elif isinstance(i, int):

                            if isinstance(nr, int):

                                if isinstance(nc, int):
                                    return dtype_func(self.h5_file.get_node(self.group_name)(start=i, stop=nr)[:, j:j+nc])
                                else:
                                    return dtype_func(self.h5_file.get_node(self.group_name)(start=i, stop=nr)[:, j])

                            else:

                                if isinstance(nc, int):
                                    return dtype_func(self.h5_file.get_node(self.group_name)[i, j:j+nc])
                                else:
                                    return dtype_func(self.h5_file.get_node(self.group_name)[i, j])

                        elif isinstance(j, np.ndarray):

                            if isinstance(i, np.ndarray) or isinstance(i, int):
                                return dtype_func(self.h5_file.get_node(self.group_name)[i, j])
                            else:
                                return dtype_func(self.h5_file.get_node(self.group_name)[:, j])

                        elif isinstance(j, int):

                            if isinstance(nc, int):

                                if isinstance(nr, int):
                                    return dtype_func(self.h5_file.get_node(self.group_name)[:, j:j+nc])
                                else:
                                    return dtype_func(self.h5_file.get_node(self.group_name)(start=i, stop=nr)[:, j])

                            else:

                                if isinstance(nc, int):
                                    return dtype_func(self.h5_file.get_node(self.group_name)[i, j:j + nc])
                                else:
                                    return dtype_func(self.h5_file.get_node(self.group_name)[i, j])

                        else:

                            if isinstance(j, np.ndarray) or isinstance(j, int):
                                return dtype_func(self.h5_file.get_node(self.group_name)[:, j])
                            else:
                                return dtype_func(self.h5_file.get_node(self.group_name).read())

            else:

                if is_flat:
                    return dtype_func(self.h5_file.root.data[i])
                else:

                    if (i is None) and (j is None):
                        return dtype_func(self.h5_file.root.data[:])
                    else:

                        if isinstance(i, np.ndarray):

                            if isinstance(j, np.ndarray) or isinstance(j, int):
                                return dtype_func(self.h5_file.root.data[i, j])
                            else:
                                return dtype_func(self.h5_file.root.data[i, :])

                        elif isinstance(i, int):

                            if not isinstance(nr, int):
                                raise TypeError('The `nr` parameter must be given with i as int.')

                            return dtype_func(self.h5_file.root.data(start=i, stop=nr)[:, j])

                        else:

                            if isinstance(j, np.ndarray) or isinstance(j, int):
                                return dtype_func(self.h5_file.root.data[:, j])
                            else:
                                return dtype_func(self.h5_file.root.data[:])

    def _set_filter(self, **kwargs):

        self.filters = tables.Filters(**kwargs)

        self.atom = tables.Atom.from_dtype(np.dtype(self.dtype))

    def close(self):
        self.h5_file.close()

    def __enter__(self):
        return self

    def __exit__(self, type, value, traceback):
        self.close()


class manage_pytables(BaseHandler):

    """
    A class to manage the PyTables information and file
    """

    def __init__(self):

        self.time_stamp = time.asctime(time.localtime(time.time()))

        self.h5_file = None

    def open_hdf_file(self, hdf_file, title='Landsat', mode='a'):

        """
        Opens an HDF file

        Args:
            hdf_file (str): The HDF file to open.
            title (Optional[str]): The HDF table title.
            mode (Optional[str])

        Attributes:
            hdf_file (object)
        """

        if hasattr(self.h5_file, 'isopen'):

            if not self.h5_file.isopen:
                self.h5_file = tables.open_file(hdf_file, mode=mode, title=title)

        else:
            self.h5_file = tables.open_file(hdf_file, mode=mode, title=title)

        self.nodes = [node._v_pathname for node in self.h5_file.walk_nodes()
                      if hasattr(node, 'title') and ('metadata' not in node._v_pathname)]

    def set_metadata(self,
                     image_name=None,
                     image_info=None,
                     meta_dict=None,
                     cloud_band_included=False,
                     sensor_override=None,
                     **kwargs):

        """
        Sets the table metadata

        Args:
            image_name (Optinoal[str]): The name of the image. Default is None.
            image_info (Optional[object]): The image ``ropen`` instance. Default is None.
            meta_dict (Optional[dict])
            cloud_band_included (Optional[bool])
            kwargs
        """

        self.image_name = image_name

        # open the image
        if isinstance(image_name, str):
            self.image_info = raster_tools.ropen(image_name)
        else:
            self.image_info = image_info

        # These are pairs to the main image,
        #   so no need to enter the metadata.
        if self.image_info:

            if ('zenith' in self.image_info.filename.lower()) or \
                    ('azimuth' in self.image_info.filename.lower()) or \
                    ('mask' in self.image_info.filename.lower()):

                if 'zenith' in self.image_info.filename.lower():
                    pair_attr = 'zenith'
                elif 'azimuth' in self.image_info.filename.lower():
                    pair_attr = 'azimuth'
                elif 'mask' in self.image_info.filename.lower():
                    pair_attr = 'mask'
                else:
                    pair_attr = 'none'

                self.meta_dict = dict()
                self.name_dict = dict(filename=self.image_info.filename[:-10],
                                      attribute=pair_attr)

                return

        if self.image_info:
            self.f_base, f_ext = os.path.splitext(self.image_info.filename)

        if isinstance(meta_dict, dict):
            self.meta_dict = copy(meta_dict)
        else:
            self.meta_dict = dict()

        if kwargs:

            for key, value in viewitems(kwargs):
                self.meta_dict[key] = value

        if 'filename' not in self.meta_dict:
            self.meta_dict['filename'] = self.image_info.filename[:-10]

        if 'storage' not in self.meta_dict:
            self.meta_dict['storage'] = self.image_info.storage.lower()

        if 'left' not in self.meta_dict:
            self.meta_dict['left'] = self.image_info.left

        if 'top' not in self.meta_dict:
            self.meta_dict['top'] = self.image_info.top

        if 'right' not in self.meta_dict:
            self.meta_dict['right'] = self.image_info.right

        if 'bottom' not in self.meta_dict:
            self.meta_dict['bottom'] = self.image_info.bottom

        if 'cell_size' not in self.meta_dict:
            self.meta_dict['cell_size'] = self.image_info.cellY

        if 'projection' not in self.meta_dict:
            self.meta_dict['projection'] = self.image_info.projection

        if 'rows' not in self.meta_dict:
            self.meta_dict['rows'] = self.image_info.rows

        if 'columns' not in self.meta_dict:
            self.meta_dict['columns'] = self.image_info.cols

        # if hasattr(self.image_info, 'path'):
        #     self.meta_dict['path'] = self.image_info.path
        # else:
        #     self.meta_dict['path'] = \
        #         self.image_info.filename[self.image_info.filename.find('p')+1:self.image_info.filename.find('r')]

        # if hasattr(self.image_info, 'row'):
        #     self.meta_dict['row'] = self.image_info.row
        # else:
        #     self.meta_dict['row'] = \
        #         self.image_info.filename[self.image_info.filename.find('r')+1:self.image_info.filename.find('_')]

        if 'bands' not in self.meta_dict:

            if cloud_band_included:
                self.meta_dict['bands'] = self.image_info.bands - 1
            else:
                self.meta_dict['bands'] = self.image_info.bands

        if 'attribute' not in self.meta_dict:
            self.meta_dict['attribute'] = self.meta_dict['filename'][self.meta_dict['filename'].rfind('_')+1:].lower()

        if 'Id' not in self.meta_dict:
            self.meta_dict['Id'] = self.meta_dict['filename'].replace('_' + self.meta_dict['attribute'], '')

        self.name_dict = dict(filename=self.meta_dict['filename'], attribute=self.meta_dict['attribute'])

        # if 'filename' in self.meta_dict:
        #     del self.meta_dict['filename']

        # if 'attribute' in self.meta_dict:
        #     del self.meta_dict['attribute']

        if ('satellite' not in self.meta_dict) or ('real_sensor' not in self.meta_dict) or \
                ('sensor' not in self.meta_dict):

            if isinstance(sensor_override, str):

                self.meta_dict['sensor'] = sensor_override
                self.meta_dict['real_sensor'] = sensor_override
                self.meta_dict['satellite'] = 'SRTM'

            else:

                if '_etm_' in self.image_info.filename.lower():

                    self.meta_dict['satellite'] = 'Landsat'
                    self.meta_dict['real_sensor'] = 'ETM'

                    if 'pan-sharp57' in self.image_info.filename.lower():
                        self.meta_dict['sensor'] = 'pan-sharp57'
                    else:
                        self.meta_dict['sensor'] = 'ETM'

                elif '_tm_' in self.image_info.filename.lower():

                    self.meta_dict['satellite'] = 'Landsat'
                    self.meta_dict['real_sensor'] = 'TM'

                    if 'pan-sharp57' in self.image_info.filename.lower():
                        self.meta_dict['sensor'] = 'pan-sharp57'
                    else:
                        self.meta_dict['sensor'] = 'TM'

                elif '_oli_tirs_' in self.image_info.filename.lower():

                    self.meta_dict['satellite'] = 'Landsat'
                    self.meta_dict['real_sensor'] = 'OLI TIRS'

                    if 'pan-sharp57' in self.image_info.filename.lower():
                        self.meta_dict['sensor'] = 'pan-sharp57'
                    else:
                        self.meta_dict['sensor'] = 'OLI TIRS'

                elif (self.sensor == 'HLS') and ('.l30.' in self.image_info.filename.lower()):

                    self.meta_dict['sensor'] = 'HLS'
                    self.meta_dict['real_sensor'] = 'OLI TIRS'
                    self.meta_dict['satellite'] = 'Landsat'

                elif (self.sensor == 'HLS') and ('.s30.' in self.image_info.filename.lower()):

                    self.meta_dict['sensor'] = 'HLS'
                    self.meta_dict['real_sensor'] = 'Sentinel2'
                    self.meta_dict['satellite'] = 'Sentinel2'

                elif self.sensor == 'MODIS':

                    self.meta_dict['sensor'] = 'MODIS'
                    self.meta_dict['real_sensor'] = 'MODIS'
                    self.meta_dict['satellite'] = 'MODIS'

                elif self.sensor == 'Sentinel-10m':

                    self.meta_dict['sensor'] = 'Sentinel2-10m'
                    self.meta_dict['real_sensor'] = 'Sentinel2'
                    self.meta_dict['satellite'] = 'Sentinel2'

                elif self.sensor == 'Sentinel-20m':

                    self.meta_dict['sensor'] = 'Sentinel2-20m'
                    self.meta_dict['real_sensor'] = 'Sentinel2'
                    self.meta_dict['satellite'] = 'Sentinel2'

                else:

                    print(self.image_info.filename)
                    raise ValueError('The sensor could not be found within the file name.')

        if 'cell_size' not in self.meta_dict:

            if '.l30.' in self.image_info.filename.lower() or '.s30.' in self.image_info.filename.lower():

                # TODO: temporary fix for 1m read-in with the HLS HDF data
                self.meta_dict['cell_size'] = 30.
                # self.meta_dict['path'] = self.image_info.filename[
                #                          self.image_info.filename.find('.T')+2:self.image_info.filename.find('.T')+4]
                # self.meta_dict['row'] = self.image_info.filename[
                #                         self.image_info.filename.find('.T')+4:self.image_info.filename.find('.T')+7]

            elif 'mcd' in self.image_info.filename.lower():
                self.meta_dict['cell_size'] = 500.

        if ('year' not in self.meta_dict) or ('date' not in self.meta_dict) or \
                ('jd' not in self.meta_dict) or ('jdr' not in self.meta_dict):

            if '_pan-sharp57_' in self.f_base.lower():

                self.year = self.f_base.lower()[self.f_base.lower().find('sharp')+8:self.f_base.lower().find('sharp')+12]
                self.date = self.f_base.lower()[self.f_base.lower().find('sharp')+13:self.f_base.lower().find('sharp')+17]

            elif ('_etm_' in self.f_base.lower()) or ('_tm_' in self.f_base.lower()):

                self.year = self.f_base.lower()[self.f_base.lower().find('tm')+3:self.f_base.lower().find('tm')+7]
                self.date = self.f_base.lower()[self.f_base.lower().find('tm')+8:self.f_base.lower().find('tm')+12]

            elif '_oli_tirs_' in self.f_base.lower():

                self.year = self.f_base.lower()[self.f_base.lower().find('tirs')+5:self.f_base.lower().find('tirs')+9]
                self.date = self.f_base.lower()[self.f_base.lower().find('tirs')+10:self.f_base.lower().find('tirs')+14]

            elif 'hls' in self.image_info.filename.lower():

                n = self.grid_info['name']
                year_date = self.f_base[self.f_base.find(n)+len(n)+1:self.f_base.find(n)+len(n)+8]

                self.year = year_date[:4]
                jd = year_date[4:]

                date = rad_calibration.julian2date(jd, self.year)
                self.date = '{:02d}{:02d}'.format(date[0], date[1])

            elif self.sensor in ['Sentinel-10m', 'Sentinel-20m']:

                file_info = self.f_base.split('_')

                year_date = file_info[3]

                self.year = year_date[:4]
                self.date = year_date[4:8]

            elif self.image_info.filename.lower().startswith('mod') or self.image_info.filename.lower().startswith('myd'):

                try:
                    int(self.f_base[self.f_base.find('.') + 1])
                    bst = int(self.f_base.find('.') + 1)
                except:
                    bst = int(self.f_base.find('.') + 2)

                date_info = self.f_base[bst:bst+7]

                self.year = date_info[:4]
                date = date_info[-3:]

                date = rad_calibration.julian2date(date, self.year)
                self.date = '{:02d}{:02d}'.format(date[0], date[1])

            else:
                self.year = -999

            if int(self.year) != -999:

                self.meta_dict['year'] = int(self.year)
                self.meta_dict['date'] = self.date

                self.meta_dict['jd'] = rad_calibration.date2julian(self.meta_dict['date'][:2],
                                                                   self.meta_dict['date'][2:],
                                                                   self.meta_dict['year'])

                self.meta_dict['jdr'] = JD_DICT['{:d}-{:03d}'.format(self.meta_dict['year'], self.meta_dict['jd'])]

        if 'utm' not in self.meta_dict:
            self.meta_dict['utm'] = int(self.grid_info['utm'])

        if 'latitude' not in self.meta_dict:
            self.meta_dict['latitude'] = self.grid_info['latitude']

        if 'grid' not in self.meta_dict:
            self.meta_dict['grid'] = self.grid_info['grid']

    def get_groups(self, grid_info, sensor):

        self.grid_info = grid_info
        self.sensor = sensor

        # The end node group name
        self.node_name = '/{UTM}/{LAT}/{GRID}/{SENSOR}'.format(UTM=str(self.grid_info['utm']),
                                                               LAT=str(self.grid_info['latitude']),
                                                               GRID=str(self.grid_info['grid']),
                                                               SENSOR=self.sensor)

        self.group_utm = '/{UTM}'.format(UTM=str(grid_info['utm']))

        self.group_latitude = '{GUTM}/{LAT}'.format(GUTM=self.group_utm,
                                                    LAT=str(self.grid_info['latitude']))

        self.group_grid = '{GLAT}/{GRID}'.format(GLAT=self.group_latitude,
                                                 GRID=str(self.grid_info['grid']))

    def add_groups(self):

        """Adds the groups to the HDF file"""

        # nodes = [node._v_title for node in self.h5_file.walk_groups()]

        # UTM group
        try:
            self.h5_file.get_node(self.group_utm)
        except:
            self.h5_file.create_group('/', str(self.grid_info['utm']), 'UTM')

        # Latitude group
        try:
            self.h5_file.get_node(self.group_latitude)
        except:
            self.h5_file.create_group(self.group_utm, self.grid_info['latitude'], 'LATITUDE')

        # Grid group
        try:
            self.h5_file.get_node(self.group_grid)
        except:
            self.h5_file.create_group(self.group_latitude, self.grid_info['grid'], 'GRID')

        # Sensor group
        try:
            self.h5_file.get_node(self.node_name)
        except:
            self.h5_file.create_group(self.group_grid, self.sensor, 'SENSOR')

    def remove_array_group(self, group2remove):

        """
        Args:
            group2remove (str)

        Example:
            pt.open_hdf_file('py_table.h5', 'Landsat')
            pt.remove_array_group('/2000/p218r63/ETM/p218r63_etm_2000_1117_ndvi')
            pt.close_hdf()
        """

        try:

            print('Removing array {} ...'.format(group2remove))

            self.h5_file.remove_node(group2remove)

        except:
            print('{} does not exist'.format(group2remove))

    def remove_table_group(self, path2remove, row2remove, sensor2remove, year2remove, date2remove):

        """
        Args:
            path2remove (int)
            row2remove (int)
            sensor2remove (str)
            year2remove (str)
            date2remove (str)

        Example:
            pt.open_hdf_file('py_table.h5', 'Landsat')
            pt.remove_table_group(218, 63, 'ETM', '2000', '1117')
            pt.close_hdf()
        """

        try:
            table = self.h5_file.root.metadata
        except:
            print('The table does not have metadata.')
            return

        full_list = True

        while full_list:

            result = [ri for ri, row in enumerate(table.iterrows()) if row['path'] == int(path2remove) and
                      row['row'] == int(row2remove) and row['sensor'] == str(sensor2remove).upper() and
                      row['year'] == str(year2remove) and row['date'] == str(date2remove)]

            # Remove only one row because the
            #   table is updated.
            if result:

                print('Removing {} from table...'.format(','.join([str(path2remove), str(row2remove),
                                                                   sensor2remove, year2remove, date2remove])))

                table.remove_row(result[0])

            else:
                full_list = False

    def add_table(self, table_name='metadata', separate_rows=False):

        """Adds the table to the HDF file"""

        if self.meta_dict:

            nodes = [node._v_title for node in self.h5_file.walk_nodes()]

            if table_name == 'metadata':

                if 'metadata' not in nodes:
                    self.table = self.h5_file.create_table('/', table_name, SensorInfo, table_name)
                else:
                    self.table = self.h5_file.root.metadata

            elif table_name == 'order':

                if 'order' not in nodes:
                    self.table = self.h5_file.create_table('/', table_name, OrderInfo, table_name)
                else:
                    self.table = self.h5_file.root.order

            # Check if the id has been entered.
            table_query = """(Id == "{}") & (utm == {:d}) & \
            (latitude == "{}") & (grid == "{}")""".format(self.meta_dict['Id'],
                                                          self.meta_dict['utm'],
                                                          self.meta_dict['latitude'],
                                                          self.meta_dict['grid'])

            if not [x for x in self.table.where(table_query)]:

                if separate_rows:

                    # Each key-value pair is a separate row

                    for meta_dict_sub in self.meta_dict:

                        pointer = self.table.row

                        for mkey, mvalue in viewitems(meta_dict_sub):
                            pointer[mkey] = mvalue

                        pointer.append()

                else:

                    pointer = self.table.row

                    for mkey, mvalue in viewitems(self.meta_dict):
                        pointer[mkey] = mvalue

                    pointer.append()

            # Commit changes to disk.
            self.table.flush()
            self.h5_file.flush()

            self.table = None
            pointer = None
            nodes = None

    def set_image_node(self, file_name, extension, strip_str):

        d_name, f_name = os.path.split(file_name)
        self.image_base, __ = os.path.splitext(f_name)

        if strip_str:
            self.image_base = self.image_base[:-6]

        if isinstance(extension, str):
            self.image_node = '{}/{}_{}'.format(self.node_name, self.image_base, extension)
        else:
            self.image_node = '{}/{}'.format(self.node_name, self.image_base)

    def check_array_node(self, file_name, extension=None, strip_str=False):

        """
        Checks if the image array has already been created

        Args:
            file_name (str): The base file name to open.

        Returns:
            True if the array has been created and False if it does not exist

            '/utm/latitude/grid/Landsat/p224r84_oli_tirs_2016_0710_ndvi'
        """

        self.array_node = None

        self.set_image_node(file_name, extension, strip_str)

        try:
            self.array_node = self.h5_file.get_node(self.image_node)
            return True
        except:
            return False

    def query_file(self, path, row):

        self.table = self.h5_file.root.metadata

        existing_files = [table_row['filename']
                          for table_row in self.table.where("""(path == {:d}) & (row == {:d})""".format(int(path),
                                                                                                        int(row)))]

        for existing_file in existing_files:
            print(existing_file)

    def write2file(self, file_name, out_name, path, row, sensor, year):

        """
        Example:
            >>> from mappy.utilities.landsat.pytables import manage_pytables
            >>> pt = manage_pytables()
            >>> pt.open_hdf_file('/2000_p228.h5', 'Landsat')
            >>> pt.write2file('p226r80_etm_2000_0110_ndvi.tif', '/out_image.tif', '2000', 226, 80, 'ETM')
        """

        try:
            table = self.h5_file.root.metadata
        except:
            print('The table does not have metadata.')
            return

        # First get the image information.
        result = [(x['filename'], x['rows'], x['columns'], x['bands'], x['projection'], x['cell_size'], \
                   x['left'], x['top'], x['right'], x['bottom'], x['storage'])
                  for x in table.where("""(filename == "%s")""" % file_name)][0]

        group_name = '/{}/p{:d}r{:d}/{}/{}'.format(str(year), int(path), int(row), sensor.upper(),
                                                   result[0].replace('.tif', ''))

        array2write = self.get_array(group_name, 0, 0, result[1], result[2])

        # Create the output file.
        # out_rst = raster_tools.create_raster(out_name, None, rows=result[1], cols=result[2], bands=result[3],
        #                                      projection=result[4], cellY=result[5], cellX=-result[5], left=result[6],
        #                                      top=result[7])

        with raster_tools.ropen('create', rows=result[1], cols=result[2], bands=result[3], 
                                projection=result[4], cellY=result[5], cellX=-result[5], 
                                left=result[6], top=result[7], right=result[8], 
                                bottom=result[9], storage=result[10]) as o_info:
    
            raster_tools.write2raster(array2write, out_name, o_info=o_info, flush_final=True)
    
            self.close_hdf()
        
        o_info = None

    def close_hdf(self):

        """
        Closes the HDF file
        """

        if hasattr(self, 'h5_file'):

            if hasattr(self.h5_file, 'isopen'):

                if self.h5_file.isopen:
                    self.h5_file.close()

        self.h5_file = None

    def close_image(self):

        """Closes the input image"""

        if hasattr(self, 'image_info'):

            if hasattr(self.image_info, 'close'):
                self.image_info.close()

        self.image_info = None


def pytables(inputs,
             hdf_file,
             image_info=None,
             title='Landsat',
             method='put',
             group=None,
             table_row=None,
             meta_dict=None,
             out_name=None,
             chunk=False,
             node_title=None,
             array_type='c',
             grid_infos=None,
             sensor=None,
             complib='blosc',
             complevel=5,
             shuffle=True,
             cloud_band_included=False,
             sensor_override=None,
             **kwargs):
    
    """
    Inserts images into a HDF file
    
    Args:
        inputs (str list or ndarray): A list of images to insert or a ndarray to insert. If ``inputs`` 
            is equal to an ndarray, then ``image_info`` must also be given.
        hdf_file (str): The HDF file to save images to.
        image_info (Optional[bool]): An ``ropen`` image object, required if ``inputs`` is a ndarray.
        title (Optional[str]): The HDF table title. Default is 'Landsat'.
        method (Optional[str]): The tables method. Default is 'put', or put data into a table. Choices are
            ['put', 'remove'].
        group (Optional[str]): A group array to remove. Default is None.
        table_row (Optional[list]): A table row list to remove. Default is []. Given as [int path, int row,
            str sensor, str year, str monthday].
        
    Returns:
        None, writes to ``hdf_file``.
        
    Examples:
        >>> from mappy.utilities.landsat import pytables
        >>>
        >>> # save two images to a HDF file
        >>> pytables(['/p228r78_etm_2000_0716.tif', '/p228r78_etm_2000_0920.tif'],
        >>>          '/2000_p228.h5')
        >>>
        >>> # remove an array group
        >>> pytables([], '/2000_p218.h5', method='remove', group='/2000/p218r63/ETM/p218r63_etm_2000_1117_ndvi')
        >>>
        >>> # remove a table row group
        >>> pytables([], '/2000_p218.h5', method='remove', table_row=[218, 63, 'ETM', '2000', '1117'])
    """
    # import gc
    pt = manage_pytables()

    # open the HDF file
    pt.open_hdf_file(hdf_file, title=title)

    group_sensor = sensor_override if isinstance(sensor_override, str) else sensor

    if method == 'put':

        if isinstance(inputs, list):

            for image_input, grid_info in zip(inputs, grid_infos):

                pt.get_groups(grid_info, group_sensor)

                info_dict = dict()

                for band in ['cblue', 'blue', 'green', 'red', 'nir', 'midir', 'farir',
                             'rededge', 'rededge2', 'rededge3', 'wv', 'cirrus']:

                    if band in grid_info:
                        info_dict[band] = grid_info[band]

                info_dict['clear'] = grid_info['clear']
                info_dict['filename'] = grid_info['filename']

                if kwargs:

                    for k, v in viewitems(kwargs):
                        info_dict[k] = v

                # Create the metadata
                pt.set_metadata(image_input,
                                meta_dict=meta_dict,
                                cloud_band_included=cloud_band_included,
                                sensor_override=sensor_override,
                                **info_dict)

                pt.add_groups()

                pt.add_table()

                pt.add_array(array_type=array_type,
                             cloud_band_included=cloud_band_included,
                             complib=complib,
                             complevel=complevel,
                             shuffle=shuffle)

        elif isinstance(inputs, np.ndarray):

            if not image_info:
                raise NameError('\nThe image info needs to be given.\n')

            # create the metadata
            pt.set_metadata(image_info=image_info,
                            meta_dict=meta_dict,
                            cloud_band_included=cloud_band_included,
                            sensor_override=sensor_override,
                            **kwargs)

            pt.get_groups(pt.meta_dict, group_sensor)

            pt.add_groups()

            pt.add_table()

            pt.add_array(image_array=inputs,
                         chunk=chunk,
                         node_title=node_title,
                         array_type=array_type,
                         complib=complib,
                         complevel=complevel,
                         shuffle=shuffle)

    elif method == 'remove':

        if isinstance(group, str):
            pt.remove_array_group(group)
        elif table_row:
            pt.remove_table_group(table_row[0], table_row[1], table_row[2], table_row[3], table_row[4])

    elif method == 'write':

        pt.write2file(inputs[0], out_name, table_row[0], table_row[1], table_row[2], table_row[3])

    pt.close_hdf()


def _examples():

    sys.exit("""\

    # Insert two images into a HDF file.
    pytables.py -i /p228r78_2000_0716.tif /p228r78_2000_0920.tif --hdf /2000_p228.h5

    # Remove an array group.
    pytables.py -i dummy --hdf /2000_p218.h5 --method remove --group /2000/p218r63/ETM/p218r63_etm_2000_1117_ndvi

    # Remove a table row group.
    pytables.py -i dummy --hdf /2000_p218.h5 --method remove --table_row 281,63,ETM,2000,1117

    # Write an array to a GeoTiff
    pytables.py -i p226r80_etm_2000_0110_ndvi.tif -o /out_name.tif --hdf /2000_p226.h5 --method write --table_row 226,80,ETM,2000,0110

    """)


def main():

    parser = argparse.ArgumentParser(description='Manage PyTables',
                                     formatter_class=argparse.ArgumentDefaultsHelpFormatter)

    parser.add_argument('-e', '--examples', dest='examples', action='store_true', help='Show usage examples and exit')
    parser.add_argument('-i', '--inputs', dest='inputs', help='The input image list', default=[], nargs='+')
    parser.add_argument('-o', '--output', dest='output', help='The output image with -m write', default=None)
    parser.add_argument('--hdf', dest='hdf', help='The HDF file to open', default=None)
    parser.add_argument('-t', '--title', dest='title', help='The table title', default='Landsat')
    parser.add_argument('-m', '--method', dest='method', help='The tables method', default='put',
                        choices=['put', 'remove', 'write'])
    parser.add_argument('-g', '--group', dest='group', help='The array group to remove', default=None)
    parser.add_argument('-tr', '--table_row', dest='table_row', help='The table row list to remove', default=None)

    args = parser.parse_args()

    if args.examples:
        _examples()

    if args.table_row:
        args.table_row = args.table_row.split(',')
        args.table_row[0] = int(args.table_row[0])
        args.table_row[1] = int(args.table_row[1])

    print('\nStart date & time --- (%s)\n' % time.asctime(time.localtime(time.time())))

    start_time = time.time()

    pytables(args.inputs, args.hdf, title=args.title, method=args.method,
             group=args.group, table_row=args.table_row, out_name=args.output)

    print('\nEnd data & time -- (%s)\nTotal processing time -- (%.2gs)\n' %
          (time.asctime(time.localtime(time.time())), (time.time()-start_time)))


if __name__ == '__main__':
    main()
