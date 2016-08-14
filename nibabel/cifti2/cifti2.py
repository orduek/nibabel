# emacs: -*- mode: python-mode; py-indent-offset: 4; indent-tabs-mode: nil -*-
# vi: set ft=python sts=4 ts=4 sw=4 et:
### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ##
#
#   See COPYING file distributed along with the NiBabel package for the
#   copyright and license terms.
#
### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ##
''' Read / write access to CIfTI2 image format

Format of the NIFTI2 container format described here:

    http://www.nitrc.org/forum/message.php?msg_id=3738

Definition of the CIFTI2 header format and file extensions here:

    https://www.nitrc.org/forum/attachment.php?attachid=333&group_id=454&forum_id=1955

'''
from __future__ import division, print_function, absolute_import
import re
import collections

from .. import xmlutils as xml
from ..filebasedimages import FileBasedHeader
from ..dataobj_images import DataobjImage
from ..nifti2 import Nifti2Image, Nifti2Header
from ..arrayproxy import reshape_dataobj


def _float_01(val):
    out = float(val)
    if out < 0 or out > 1:
        raise ValueError('Float must be between 0 and 1 inclusive')
    return out


class CIFTI2HeaderError(Exception):
    """ Error in CIFTI2 header
    """


CIFTI_MAP_TYPES = ('CIFTI_INDEX_TYPE_BRAIN_MODELS',
                   'CIFTI_INDEX_TYPE_PARCELS',
                   'CIFTI_INDEX_TYPE_SERIES',
                   'CIFTI_INDEX_TYPE_SCALARS',
                   'CIFTI_INDEX_TYPE_LABELS')

CIFTI_MODEL_TYPES = ('CIFTI_MODEL_TYPE_SURFACE',
                     'CIFTI_MODEL_TYPE_VOXELS')

CIFTI_SERIESUNIT_TYPES = ('SECOND',
                          'HERTZ',
                          'METER',
                          'RADIAN')

CIFTI_BrainStructures = ('CIFTI_STRUCTURE_ACCUMBENS_LEFT',
                         'CIFTI_STRUCTURE_ACCUMBENS_RIGHT',
                         'CIFTI_STRUCTURE_ALL_WHITE_MATTER',
                         'CIFTI_STRUCTURE_ALL_GREY_MATTER',
                         'CIFTI_STRUCTURE_AMYGDALA_LEFT',
                         'CIFTI_STRUCTURE_AMYGDALA_RIGHT',
                         'CIFTI_STRUCTURE_BRAIN_STEM',
                         'CIFTI_STRUCTURE_CAUDATE_LEFT',
                         'CIFTI_STRUCTURE_CAUDATE_RIGHT',
                         'CIFTI_STRUCTURE_CEREBELLAR_WHITE_MATTER_LEFT',
                         'CIFTI_STRUCTURE_CEREBELLAR_WHITE_MATTER_RIGHT',
                         'CIFTI_STRUCTURE_CEREBELLUM',
                         'CIFTI_STRUCTURE_CEREBELLUM_LEFT',
                         'CIFTI_STRUCTURE_CEREBELLUM_RIGHT',
                         'CIFTI_STRUCTURE_CEREBRAL_WHITE_MATTER_LEFT',
                         'CIFTI_STRUCTURE_CEREBRAL_WHITE_MATTER_RIGHT',
                         'CIFTI_STRUCTURE_CORTEX',
                         'CIFTI_STRUCTURE_CORTEX_LEFT',
                         'CIFTI_STRUCTURE_CORTEX_RIGHT',
                         'CIFTI_STRUCTURE_DIENCEPHALON_VENTRAL_LEFT',
                         'CIFTI_STRUCTURE_DIENCEPHALON_VENTRAL_RIGHT',
                         'CIFTI_STRUCTURE_HIPPOCAMPUS_LEFT',
                         'CIFTI_STRUCTURE_HIPPOCAMPUS_RIGHT',
                         'CIFTI_STRUCTURE_OTHER',
                         'CIFTI_STRUCTURE_OTHER_GREY_MATTER',
                         'CIFTI_STRUCTURE_OTHER_WHITE_MATTER',
                         'CIFTI_STRUCTURE_PALLIDUM_LEFT',
                         'CIFTI_STRUCTURE_PALLIDUM_RIGHT',
                         'CIFTI_STRUCTURE_PUTAMEN_LEFT',
                         'CIFTI_STRUCTURE_PUTAMEN_RIGHT',
                         'CIFTI_STRUCTURE_THALAMUS_LEFT',
                         'CIFTI_STRUCTURE_THALAMUS_RIGHT')


def _value_if_klass(val, klass):
    if val is None or isinstance(val, klass):
        return val
    raise ValueError('Not a valid %s instance.' % klass.__name__)


def _underscore(string):
    """ Convert a string from CamelCase to underscored """
    string = re.sub(r'([A-Z]+)([A-Z][a-z])', r'\1_\2', string)
    return re.sub(r'([a-z0-9])([A-Z])', r'\1_\2', string).lower()


class Cifti2MetaData(xml.XmlSerializable, collections.MutableMapping):
    """ A list of name-value pairs

    Attributes
    ----------
    data : list of (name, value) tuples
    """
    def __init__(self, metadata=None):
        self.data = collections.OrderedDict()
        if metadata is not None:
            self.update(metadata)

    def __getitem__(self, key):
        return self.data[key]

    def __setitem__(self, key, value):
        self.data[key] = value

    def __delitem__(self, key):
        del self.data[key]

    def __len__(self):
        return len(self.data)

    def __iter__(self):
        return iter(self.data)

    def difference_update(self, metadata):
        """Remove metadata key-value pairs

        Parameters
        ----------
        metadata : dict-like datatype

        Returns
        -------
        None

        """
        if metadata is None:
            raise ValueError("The metadata parameter can't be None")
        pairs = dict(metadata)
        for k in pairs:
            del self.data[k]

    def _to_xml_element(self):
        metadata = xml.Element('MetaData')

        for name_text, value_text in self.data.items():
            md = xml.SubElement(metadata, 'MD')
            name = xml.SubElement(md, 'Name')
            name.text = str(name_text)
            value = xml.SubElement(md, 'Value')
            value.text = str(value_text)
        return metadata


class Cifti2LabelTable(xml.XmlSerializable, collections.MutableMapping):
    """ Cifti2 label table: a sequence of ``Cifti2Label``s
    """

    def __init__(self):
        self._labels = collections.OrderedDict()

    def __len__(self):
        return len(self._labels)

    def __getitem__(self, key):
        return self._labels[key]

    def append(self, label):
        self[label.key] = label

    def __setitem__(self, key, value):
        if isinstance(value, Cifti2Label):
            if key != value.key:
                raise ValueError("The key and the label's key must agree")
            self._labels[key] = value
            return
        if len(value) != 5:
            raise ValueError('Value should be length 5')
        try:
            self._labels[key] = Cifti2Label(*([key] + list(value)))
        except ValueError:
            raise ValueError('Key should be int, value should be sequence '
                             'of str and 4 floats between 0 and 1')

    def __delitem__(self, key):
        del self._labels[key]

    def __iter__(self):
        return iter(self._labels)

    def _to_xml_element(self):
        if len(self) == 0:
            raise CIFTI2HeaderError('LabelTable element requires at least 1 label')
        labeltable = xml.Element('LabelTable')
        for ele in self._labels.values():
            labeltable.append(ele._to_xml_element())
        return labeltable


class Cifti2Label(xml.XmlSerializable):
    """ Cifti2 label: association of integer key with a name and RGBA values

    Attribute descriptions are from the CIFTI-2 spec dated 2014-03-01.
    For all color components, value is floating point with range 0.0 to 1.0.

    Attributes
    ----------
    key : int, optional
        Integer, data value which is assigned this name and color.
    label : str, optional
        Name of the label.
    red : float, optional
        Red color component for label (between 0 and 1).
    green : float, optional
        Green color component for label (between 0 and 1).
    blue : float, optional
        Blue color component for label (between 0 and 1).
    alpha : float, optional
        Alpha color component for label (between 0 and 1).
    """
    def __init__(self, key=0, label='', red=0., green=0., blue=0., alpha=0.):
        self.key = int(key)
        self.label = str(label)
        self.red = _float_01(red)
        self.green = _float_01(green)
        self.blue = _float_01(blue)
        self.alpha = _float_01(alpha)

    @property
    def rgba(self):
        """ Returns RGBA as tuple """
        return (self.red, self.green, self.blue, self.alpha)

    def _to_xml_element(self):
        if self.label is '':
            raise CIFTI2HeaderError('Label needs a name')
        try:
            v = int(self.key)
        except ValueError:
            raise CIFTI2HeaderError('The key must be an integer')
        for c_ in ('red', 'blue', 'green', 'alpha'):
            try:
                v = _float_01(getattr(self, c_))
            except ValueError:
                raise CIFTI2HeaderError(
                    'Label invalid %s needs to be a float between 0 and 1. '
                    'and it is %s' % (c_, v)
                )

        lab = xml.Element('Label')
        lab.attrib['Key'] = str(self.key)
        lab.text = str(self.label)

        for name in ('red', 'green', 'blue', 'alpha'):
            val = getattr(self, name)
            attr = '0' if val == 0 else '1' if val == 1 else str(val)
            lab.attrib[name.capitalize()] = attr
        return lab


class Cifti2NamedMap(xml.XmlSerializable):
    """Cifti2 named map: association of name and optional data with a map index

    Associates a name, optional metadata, and possibly a LabelTable with an
    index in a map.

    Attributes
    ----------
    map_name : str
        Name of map
    metadata : None or Cifti2MetaData
        Metadata associated with named map
    label_table : None or Cifti2LabelTable
        Label table associated with named map
    """
    def __init__(self, map_name=None, metadata=None, label_table=None):
        self.map_name = map_name
        self.metadata = metadata
        self.label_table = label_table

    @property
    def metadata(self):
        return self._metadata

    @metadata.setter
    def metadata(self, metadata):
        """ Set the metadata for this NamedMap

        Parameters
        ----------
        meta : Cifti2MetaData

        Returns
        -------
        None
        """
        self._metadata = _value_if_klass(metadata, Cifti2MetaData)

    @property
    def label_table(self):
        return self._label_table

    @label_table.setter
    def label_table(self, label_table):
        """ Set the label_table for this NamedMap

        Parameters
        ----------
        label_table : Cifti2LabelTable

        Returns
        -------
        None
        """
        self._label_table = _value_if_klass(label_table, Cifti2LabelTable)

    def _to_xml_element(self):
        named_map = xml.Element('NamedMap')
        if self.metadata:
            named_map.append(self.metadata._to_xml_element())
        if self.label_table:
            named_map.append(self.label_table._to_xml_element())
        map_name = xml.SubElement(named_map, 'MapName')
        map_name.text = self.map_name
        return named_map


class Cifti2Surface(xml.XmlSerializable):
    """Cifti surface: association of brain structure and number of vertices

    "Specifies the number of vertices for a surface, when IndicesMapToDataType
    is 'CIFTI_INDEX_TYPE_PARCELS.' This is separate from the Parcel element
    because there can be multiple parcels on one surface, and one parcel may
    involve multiple surfaces."

    Attributes
    ----------
    brain_structure : str
        Name of brain structure
    surface_number_of_vertices : int
        Number of vertices on surface
    """
    def __init__(self, brain_structure=None, surface_number_of_vertices=None):
        self.brain_structure = brain_structure
        self.surface_number_of_vertices = surface_number_of_vertices

    def _to_xml_element(self):
        if self.brain_structure is None:
            raise CIFTI2HeaderError('Surface element requires at least 1 BrainStructure')
        surf = xml.Element('Surface')
        surf.attrib['BrainStructure'] = str(self.brain_structure)
        surf.attrib['SurfaceNumberOfVertices'] = str(self.surface_number_of_vertices)
        return surf


class Cifti2VoxelIndicesIJK(xml.XmlSerializable, collections.MutableSequence):
    """Cifti2 VoxelIndicesIJK: Set of voxel indices contained in a structure

    "Identifies the voxels that model a brain structure, or participate in a
    parcel. Note that when this is a child of BrainModel, the IndexCount
    attribute of the BrainModel indicates the number of voxels contained in
    this element."

    Each element of this sequence is a triple of integers.
    """
    def __init__(self, indices=None):
        self._indices = []
        if indices is not None:
            self.extend(indices)

    def __len__(self):
        return len(self._indices)

    def __delitem__(self, index):
        if not isinstance(index, int) and len(index) > 1:
            raise NotImplementedError
        del self._indices[index]

    def __getitem__(self, index):
        if isinstance(index, int):
            return self._indices[index]
        elif len(index) == 2:
            if not isinstance(index[0], int):
                raise NotImplementedError
            return self._indices[index[0]][index[1]]
        else:
            raise ValueError('Only row and row,column access is allowed')

    def __setitem__(self, index, value):
        if isinstance(index, int):
            try:
                value = [int(v) for v in value]
                if len(value) != 3:
                    raise ValueError('rows are triples of ints')
                self._indices[index] = value
            except ValueError:
                raise ValueError('value must be a triple of ints')
        elif len(index) == 2:
            try:
                if not isinstance(index[0], int):
                    raise NotImplementedError
                value = int(value)
                self._indices[index[0]][index[1]] = value
            except ValueError:
                raise ValueError('value must be an int')
        else:
            raise ValueError

    def insert(self, index, value):
        if not isinstance(index, int) and len(index) != 1:
            raise ValueError('Only rows can be inserted')
        try:
            value = [int(v) for v in value]
            if len(value) != 3:
                raise ValueError
            self._indices.insert(index, value)
        except ValueError:
            raise ValueError('value must be a triple of int')

    def _to_xml_element(self):
        if len(self) == 0:
            raise CIFTI2HeaderError('VoxelIndicesIJK element require an index table')

        vox_ind = xml.Element('VoxelIndicesIJK')
        vox_ind.text = '\n'.join(' '.join([str(v) for v in row])
                                 for row in self._indices)
        return vox_ind


class Cifti2Vertices(xml.XmlSerializable, collections.MutableSequence):
    """Cifti2 vertices - association of brain structure and a list of vertices

    "Contains a BrainStructure type and a list of vertex indices within a
    Parcel."

    Attribute descriptions are from the CIFTI-2 spec dated 2014-03-01.
    The class behaves like a list of Vertex indices
    (which are independent for each surface, and zero-based)

    Attributes
    ----------
    brain_structure : str
        A string from the BrainStructure list to identify what surface this
        vertex list is from (usually left cortex, right cortex, or cerebellum).
    """
    def __init__(self, brain_structure=None, vertices=None):
        self._vertices = []
        if vertices is not None:
            self.extend(vertices)

        self.brain_structure = brain_structure

    def __len__(self):
        return len(self._vertices)

    def __delitem__(self, index):
        del self._vertices[index]

    def __getitem__(self, index):
        return self._vertices[index]

    def __setitem__(self, index, value):
        try:
            value = int(value)
            self._vertices[index] = value
        except ValueError:
            raise ValueError('value must be an int')

    def insert(self, index, value):
        try:
            value = int(value)
            self._vertices.insert(index, value)
        except ValueError:
            raise ValueError('value must be an int')

    def _to_xml_element(self):
        if self.brain_structure is None:
            raise CIFTI2HeaderError('Vertices element require a BrainStructure')

        vertices = xml.Element('Vertices')
        vertices.attrib['BrainStructure'] = str(self.brain_structure)

        vertices.text = ' '.join([str(i) for i in self])
        return vertices


class Cifti2Parcel(xml.XmlSerializable):
    """Cifti2 parcel: association of a name with vertices and/or voxels

    Attributes
    ----------
    name : str
        Name of parcel
    voxel_indices_ijk : None or Cifti2VoxelIndicesIJK
        Voxel indices associated with parcel
    vertices : list of Cifti2Vertices
        Vertices associated with parcel
    """
    def __init__(self, name=None, voxel_indices_ijk=None, vertices=None):
        self.name = name
        self.voxel_indices_ijk = voxel_indices_ijk
        self.vertices = vertices if vertices is not None else []

    @property
    def voxel_indices_ijk(self):
        return self._voxel_indices_ijk

    @voxel_indices_ijk.setter
    def voxel_indices_ijk(self, value):
        self._voxel_indices_ijk = _value_if_klass(value, Cifti2VoxelIndicesIJK)

    def append_cifti_vertices(self, vertices):
        """ Appends a Cifti2Vertices element to the Cifti2Parcel

        Parameters
        ----------
        vertices : Cifti2Vertices
        """
        if not isinstance(vertices, Cifti2Vertices):
            raise TypeError("Not a valid Cifti2Vertices instance")
        self.vertices.append(vertices)

    def pop_cifti2_vertices(self, ith):
        """ Pops the ith vertices element from the Cifti2Parcel """
        self.vertices.pop(ith)

    def _to_xml_element(self):
        if self.name is None:
            raise CIFTI2HeaderError('Parcel element requires a name')

        parcel = xml.Element('Parcel')
        parcel.attrib['Name'] = str(self.name)
        if self.voxel_indices_ijk:
            parcel.append(self.voxel_indices_ijk._to_xml_element())
        for vertex in self.vertices:
            parcel.append(vertex._to_xml_element())
        return parcel


class Cifti2TransformationMatrixVoxelIndicesIJKtoXYZ(xml.XmlSerializable):
    """Matrix that translates voxel indices to spatial coordinates

    Attributes
    ----------
    meter_exponent : int
        "[S]pecifies that the coordinate result from the transformation matrix
        should be multiplied by 10 to this power to get the spatial coordinates
        in meters (e.g., if this is '-3', then the transformation matrix is in
        millimeters)."
    matrix : array-like shape (4, 4)
        Affine transformation matrix from voxel indices to RAS space
    """
    # meterExponent = int
    # matrix = np.array

    def __init__(self, meter_exponent=None, matrix=None):
        self.meter_exponent = meter_exponent
        self.matrix = matrix

    def _to_xml_element(self):
        if self.matrix is None:
            raise CIFTI2HeaderError(
                'TransformationMatrixVoxelIndicesIJKtoXYZ element requires a matrix'
            )
        trans = xml.Element('TransformationMatrixVoxelIndicesIJKtoXYZ')
        trans.attrib['MeterExponent'] = str(self.meter_exponent)
        trans.text = '\n'.join(' '.join(map('{:.10f}'.format, row))
                               for row in self.matrix)
        return trans


class Cifti2Volume(xml.XmlSerializable):
    """Cifti2 volume: information about a volume for mappings that use voxels

    Attributes
    ----------
    volume_dimensions : array-like shape (3,)
        "[T]he lengthss of the three volume file dimensions that are related to
        spatial coordinates, in number of voxels. Voxel indices (which are
        zero-based) that are used in the mapping that this element applies to
        must be within these dimensions."
    transformation_matrix_voxel_indices_ijk_to_xyz \
        : Cifti2TransformationMatrixVoxelIndicesIJKtoXYZ
        Matrix that translates voxel indices to spatial coordinates
    """
    def __init__(self, volume_dimensions=None, transform_matrix=None):
        self.volume_dimensions = volume_dimensions
        self.transformation_matrix_voxel_indices_ijk_to_xyz = transform_matrix

    def _to_xml_element(self):
        if self.volume_dimensions is None:
            raise CIFTI2HeaderError('Volume element requires dimensions')

        volume = xml.Element('Volume')
        volume.attrib['VolumeDimensions'] = ','.join(
            [str(val) for val in self.volume_dimensions])
        volume.append(self.transformation_matrix_voxel_indices_ijk_to_xyz._to_xml_element())
        return volume


class Cifti2VertexIndices(xml.XmlSerializable, collections.MutableSequence):
    """Cifti2 vertex indices: vertex indices for an associated brain model

    The vertex indices (which are independent for each surface, and
    zero-based) that are used in this brain model[.] The parent
    BrainModel's ``index_count`` indicates the number of indices.
    """
    def __init__(self, indices=None):
        self._indices = []
        if indices is not None:
            self.extend(indices)

    def __len__(self):
        return len(self._indices)

    def __delitem__(self, index):
        del self._indices[index]

    def __getitem__(self, index):
        return self._indices[index]

    def __setitem__(self, index, value):
        try:
            value = int(value)
            self._indices[index] = value
        except ValueError:
            raise ValueError('value must be an int')

    def insert(self, index, value):
        try:
            value = int(value)
            self._indices.insert(index, value)
        except ValueError:
            raise ValueError('value must be an int')

    def _to_xml_element(self):
        if len(self) == 0:
            raise CIFTI2HeaderError('VertexIndices element requires indices')

        vert_indices = xml.Element('VertexIndices')
        vert_indices.text = ' '.join([str(i) for i in self])
        return vert_indices


class Cifti2BrainModel(xml.XmlSerializable):
    '''
    BrainModel element representing a mapping of the dimension to vertex or voxels.
    Mapping to vertices of voxels must be specified.

    Attributes
    ----------
        index_offset : int
            Start of the mapping
        index_count : int
            Number of elements in the array to be mapped
        model_type : str
            One of CIFTI_MODEL_TYPES
        brain_structure : str
            One of CIFTI_BrainStructures
        surface_number_of_vertices : int
            Number of vertices in the surface. Use only for surface-type structure
        voxel_indices_ijk : Cifti2VoxelIndicesIJK, optional
            Indices on the image towards where the array indices are mapped
        vertex_indices : Cifti2VertexIndices, optional
            Indices of the vertices towards where the array indices are mapped
    '''

    def __init__(self, index_offset=None, index_count=None, model_type=None,
                 brain_structure=None, n_surface_vertices=None,
                 voxel_indices_ijk=None, vertex_indices=None):
        self.index_offset = index_offset
        self.index_count = index_count
        self.model_type = model_type
        self.brain_structure = brain_structure
        self.surface_number_of_vertices = n_surface_vertices

        self.voxel_indices_ijk = voxel_indices_ijk
        self.vertex_indices = vertex_indices

    @property
    def voxel_indices_ijk(self):
        return self._voxel_indices_ijk

    @voxel_indices_ijk.setter
    def voxel_indices_ijk(self, value):
        self._voxel_indices_ijk = _value_if_klass(value, Cifti2VoxelIndicesIJK)

    @property
    def vertex_indices(self):
        return self._vertex_indices

    @vertex_indices.setter
    def vertex_indices(self, value):
        self._vertex_indices = _value_if_klass(value, Cifti2VertexIndices)

    def _to_xml_element(self):
        brain_model = xml.Element('BrainModel')

        for key in ['IndexOffset', 'IndexCount', 'ModelType', 'BrainStructure',
                    'SurfaceNumberOfVertices']:
            attr = _underscore(key)
            value = getattr(self, attr)
            if value is not None:
                brain_model.attrib[key] = str(value)
        if self.voxel_indices_ijk:
            brain_model.append(self.voxel_indices_ijk._to_xml_element())
        if self.vertex_indices:
            brain_model.append(self.vertex_indices._to_xml_element())
        return brain_model


class Cifti2MatrixIndicesMap(xml.XmlSerializable, collections.MutableSequence):
    """Class for Matrix Indices Map

    Provides a mapping between matrix indices and their interpretation.

    Attribute
    ---------
        applies_to_matrix_dimension : list of ints
            Dimensions of this matrix that follow this mapping
        indices_map_to_data_type : str one of CIFTI_MAP_TYPES
            Type of mapping to the matrix indices
        number_of_series_points : int, optional
            If it is a series, number of points in the series
        series_exponent : int, optional
            If it is a series the exponent of the increment
        series_start : float, optional
            If it is a series, starting time
        series_step : float, optional
            If it is a series, step per element
        series_unit : str, optional
            If it is a series, units
    """
    _valid_type_mappings_ = {
        Cifti2BrainModel: ('CIFTI_INDEX_TYPE_BRAIN_MODELS',),
        Cifti2Parcel: ('CIFTI_INDEX_TYPE_PARCELS',),
        Cifti2NamedMap: ('CIFTI_INDEX_TYPE_LABELS',),
        Cifti2Volume: ('CIFTI_INDEX_TYPE_SCALARS', 'CIFTI_INDEX_TYPE_SERIES'),
        Cifti2Surface: ('CIFTI_INDEX_TYPE_SCALARS', 'CIFTI_INDEX_TYPE_SERIES')
    }

    def __init__(self, applies_to_matrix_dimension,
                 indices_map_to_data_type,
                 number_of_series_points=None,
                 series_exponent=None,
                 series_start=None,
                 series_step=None,
                 series_unit=None,
                 maps=[],
                 ):
        self.applies_to_matrix_dimension = applies_to_matrix_dimension
        self.indices_map_to_data_type = indices_map_to_data_type
        self.number_of_series_points = number_of_series_points
        self.series_exponent = series_exponent
        self.series_start = series_start
        self.series_step = series_step
        self.series_unit = series_unit
        self._maps = []
        for m in maps:
            self.append(m)

    def __len__(self):
        return len(self._maps)

    def __delitem__(self, index):
        del self._maps[index]

    def __getitem__(self, index):
        return self._maps[index]

    def __setitem__(self, index, value):
        if (
            isinstance(value, Cifti2Volume) and
            (
                self.volume is not None and
                not isinstance(self._maps[index], Cifti2Volume)
            )
        ):
            raise CIFTI2HeaderError("Only one Volume can be in a MatrixIndicesMap")
        self._maps[index] = value

    def insert(self, index, value):
        if (
            isinstance(value, Cifti2Volume) and
            self.volume is not None
        ):
            raise CIFTI2HeaderError("Only one Volume can be in a MatrixIndicesMap")

        self._maps.insert(index, value)

    @property
    def named_maps(self):
        for p in self:
            if isinstance(p, Cifti2NamedMap):
                yield p

    @property
    def surfaces(self):
        for p in self:
            if isinstance(p, Cifti2Surface):
                yield p

    @property
    def parcels(self):
        for p in self:
            if isinstance(p, Cifti2Parcel):
                yield p

    @property
    def volume(self):
        for p in self:
            if isinstance(p, Cifti2Volume):
                return p
        return None

    @volume.setter
    def volume(self, volume):
        if not isinstance(volume, Cifti2Volume):
            raise ValueError("You can only set a volume with a volume")
        for i, v in enumerate(self):
            if isinstance(v, Cifti2Volume):
                break
        else:
            self.append(volume)
            return
        self[i] = volume

    @volume.deleter
    def volume(self):
        for i, v in enumerate(self):
            if isinstance(v, Cifti2Volume):
                break
        else:
            raise ValueError("No Cifti2Volume element")
        del self[i]

    @property
    def brain_models(self):
        for p in self:
            if isinstance(p, Cifti2BrainModel):
                yield p

    def _to_xml_element(self):
        if self.applies_to_matrix_dimension is None:
            raise CIFTI2HeaderError(
                'MatrixIndicesMap element requires to be applied to at least 1 dimension'
            )

        mat_ind_map = xml.Element('MatrixIndicesMap')
        dims_as_strings = [str(dim) for dim in self.applies_to_matrix_dimension]
        mat_ind_map.attrib['AppliesToMatrixDimension'] = ','.join(dims_as_strings)
        for key in ['IndicesMapToDataType', 'NumberOfSeriesPoints', 'SeriesExponent',
                    'SeriesStart', 'SeriesStep', 'SeriesUnit']:
            attr = _underscore(key)
            value = getattr(self, attr)
            if value is not None:
                mat_ind_map.attrib[key] = str(value)
        for map_ in self:
            mat_ind_map.append(map_._to_xml_element())

        return mat_ind_map


class Cifti2Matrix(xml.XmlSerializable, collections.MutableSequence):
    def __init__(self):
        self._mims = []
        self.metadata = None

    @property
    def metadata(self):
        return self._meta

    @metadata.setter
    def metadata(self, meta):
        """ Set the metadata for this Cifti2Header

        Parameters
        ----------
        meta : Cifti2MetaData

        Returns
        -------
        None
        """
        self._meta = _value_if_klass(meta, Cifti2MetaData)

    def __setitem__(self, key, value):
        if not isinstance(value, Cifti2MatrixIndicesMap):
            raise TypeError("Not a valid Cifti2MatrixIndicesMap instance")
        self._mims[key] = value

    def __getitem__(self, key):
        return self._mims[key]

    def __delitem__(self, key):
        del self._mims[key]

    def __len__(self):
        return len(self._mims)

    def insert(self, index, value):
        if not isinstance(value, Cifti2MatrixIndicesMap):
            raise TypeError("Not a valid Cifti2MatrixIndicesMap instance")
        self._mims.insert(index, value)

    def _to_xml_element(self):
        if (len(self) == 0 and self.metadata is None):
            raise CIFTI2HeaderError(
                'Matrix element requires either a MatrixIndicesMap or a Metadata element'
            )

        mat = xml.Element('Matrix')
        if self.metadata:
            mat.append(self.metadata._to_xml_element())
        for mim in self._mims:
            mat.append(mim._to_xml_element())
        return mat


class Cifti2Header(FileBasedHeader, xml.XmlSerializable):
    ''' Class for Cifti2 header extension '''

    def __init__(self, matrix=None, version="2.0"):
        FileBasedHeader.__init__(self)
        xml.XmlSerializable.__init__(self)
        self.matrix = Cifti2Matrix() if matrix is None else Cifti2Matrix()
        self.version = version

    def _to_xml_element(self):
        cifti = xml.Element('CIFTI')
        cifti.attrib['Version'] = str(self.version)
        mat_xml = self.matrix._to_xml_element()
        if mat_xml is not None:
            cifti.append(mat_xml)
        return cifti

    @classmethod
    def may_contain_header(klass, binaryblock):
        from .parse_cifti2 import _Cifti2AsNiftiHeader
        return _Cifti2AsNiftiHeader.may_contain_header(binaryblock)


class Cifti2Image(DataobjImage):
    """ Class for single file CIFTI2 format image
    """
    header_class = Cifti2Header
    valid_exts = Nifti2Image.valid_exts
    files_types = Nifti2Image.files_types
    makeable = False
    rw = True

    def __init__(self,
                 dataobj=None,
                 header=None,
                 nifti_header=None,
                 extra=None,
                 file_map=None):
        ''' Initialize image

        The image is a combination of (dataobj, header), with optional metadata
        in `nifti_header` (a NIfTI2 header).  There may be more metadata in the
        mapping `extra`. Filename / file-like objects can also go in the
        `file_map` mapping.

        Parameters
        ----------
        dataobj : object
            Object containing image data.  It should be some object that returns
            an array from ``np.asanyarray``.  It should have a ``shape``
            attribute or property.
        header : Cifti2Header instance
            Header with data for / from XML part of CIFTI2 format.
        nifti_header : None or mapping or NIfTI2 header instance, optional
            Metadata for NIfTI2 component of this format.
        extra : None or mapping
            Extra metadata not captured by `header` or `nifti_header`.
        file_map : mapping, optional
            Mapping giving file information for this image format.
        '''
        super(Cifti2Image, self).__init__(dataobj, header=header,
                                          extra=extra, file_map=file_map)
        self._nifti_header = Nifti2Header.from_header(nifti_header)

    @property
    def nifti_header(self):
        return self._nifti_header

    @classmethod
    def from_file_map(klass, file_map):
        """ Load a Cifti2 image from a file_map

        Parameters
        ----------
        file_map : file_map

        Returns
        -------
        img : Cifti2Image
            Returns a Cifti2Image
         """
        from .parse_cifti2 import _Cifti2AsNiftiImage, Cifti2Extension
        nifti_img = _Cifti2AsNiftiImage.from_file_map(file_map)

        # Get cifti2 header
        for item in nifti_img.header.extensions:
            if isinstance(item, Cifti2Extension):
                cifti_header = item.get_content()
                break
        else:
            raise ValueError('NIfTI2 header does not contain a CIFTI2 '
                             'extension')

        # Construct cifti image.
        # User array proxy object where possible
        dataobj = nifti_img.dataobj
        return Cifti2Image(reshape_dataobj(dataobj, dataobj.shape[4:]),
                           header=cifti_header,
                           nifti_header=nifti_img.header,
                           file_map=file_map)

    @classmethod
    def from_image(klass, img):
        ''' Class method to create new instance of own class from `img`

        Parameters
        ----------
        img : instance
            In fact, an object with the API of :class:`DataobjImage`.

        Returns
        -------
        cimg : instance
            Image, of our own class
        '''
        if isinstance(img, klass):
            return img
        raise NotImplementedError

    def to_file_map(self, file_map=None):
        """ Write image to `file_map` or contained ``self.file_map``

        Parameters
        ----------
        file_map : None or mapping, optional
           files mapping.  If None (default) use object's ``file_map``
           attribute instead.

        Returns
        -------
        None
        """
        from .parse_cifti2 import Cifti2Extension
        header = self._nifti_header
        extension = Cifti2Extension(content=self.header.to_xml())
        header.extensions.append(extension)
        data = reshape_dataobj(self.dataobj,
                               (1, 1, 1, 1) + self.dataobj.shape)
        # If qform not set, reset pixdim values so Nifti2 does not complain
        if header['qform_code'] == 0:
            header['pixdim'][:4] = 1
        img = Nifti2Image(data, None, header)
        img.to_file_map(file_map or self.file_map)


def load(filename):
    """ Load cifti2 from `filename`

    Parameters
    ----------
    filename : str
        filename of image to be loaded

    Returns
    -------
    img : Cifti2Image
        cifti image instance

    Raises
    ------
    ImageFileError: if `filename` doesn't look like cifti
    IOError : if `filename` does not exist
    """
    return Cifti2Image.from_filename(filename)


def save(img, filename):
    """ Save cifti to `filename`

    Parameters
    ----------
    filename : str
        filename to which to save image
    """
    Cifti2Image.instance_to_filename(img, filename)
