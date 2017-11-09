# emacs: -*- mode: python-mode; py-indent-offset: 4; indent-tabs-mode: nil -*-
# vi: set ft=python sts=4 ts=4 sw=4 et:
### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ##
#
#   See COPYING file distributed along with the NiBabel package for the
#   copyright and license terms.
#
### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ##
'''Tests for mghformat reading writing'''

import os
import io

import numpy as np

from .. import load, save
from ...openers import ImageOpener
from ..mghformat import MGHHeader, MGHError, MGHImage
from ...tmpdirs import InTemporaryDirectory
from ...fileholders import FileHolder

from nose.tools import assert_true, assert_false

from numpy.testing import (assert_equal, assert_array_equal,
                           assert_array_almost_equal, assert_almost_equal,
                           assert_raises)

from ...testing import data_path

from ...tests import test_spatialimages as tsi

MGZ_FNAME = os.path.join(data_path, 'test.mgz')

# sample voxel to ras matrix (mri_info --vox2ras)
v2r = np.array([[1, 2, 3, -13], [2, 3, 1, -11.5],
                [3, 1, 2, -11.5], [0, 0, 0, 1]], dtype=np.float32)
# sample voxel to ras - tkr matrix (mri_info --vox2ras-tkr)
v2rtkr = np.array([[-1.0, 0.0, 0.0, 1.5],
                   [0.0, 0.0, 1.0, -2.5],
                   [0.0, -1.0, 0.0, 2.0],
                   [0.0, 0.0, 0.0, 1.0]], dtype=np.float32)


def test_read_mgh():
    # test.mgz was generated by the following command
    # mri_volsynth --dim 3 4 5 2 --vol test.mgz
    # --cdircos 1 2 3 --rdircos 2 3 1 --sdircos 3 1 2
    # mri_volsynth is a FreeSurfer command
    mgz = load(MGZ_FNAME)

    # header
    h = mgz.header
    assert_equal(h['version'], 1)
    assert_equal(h['type'], 3)
    assert_equal(h['dof'], 0)
    assert_equal(h['goodRASFlag'], 1)
    assert_array_equal(h['dims'], [3, 4, 5, 2])
    assert_almost_equal(h['tr'], 2.0)
    assert_almost_equal(h['flip_angle'], 0.0)
    assert_almost_equal(h['te'], 0.0)
    assert_almost_equal(h['ti'], 0.0)
    assert_array_almost_equal(h.get_zooms(), [1, 1, 1, 2])
    assert_array_almost_equal(h.get_vox2ras(), v2r)
    assert_array_almost_equal(h.get_vox2ras_tkr(), v2rtkr)

    # data. will be different for your own mri_volsynth invocation
    v = mgz.get_data()
    assert_almost_equal(v[1, 2, 3, 0], -0.3047, 4)
    assert_almost_equal(v[1, 2, 3, 1], 0.0018, 4)


def test_write_mgh():
    # write our data to a tmp file
    v = np.arange(120)
    v = v.reshape((5, 4, 3, 2)).astype(np.float32)
    # form a MGHImage object using data and vox2ras matrix
    img = MGHImage(v, v2r)
    with InTemporaryDirectory():
        save(img, 'tmpsave.mgz')
        # read from the tmp file and see if it checks out
        mgz = load('tmpsave.mgz')
        h = mgz.header
        dat = mgz.get_data()
        # Delete loaded image to allow file deletion by windows
        del mgz
    # header
    assert_equal(h['version'], 1)
    assert_equal(h['type'], 3)
    assert_equal(h['dof'], 0)
    assert_equal(h['goodRASFlag'], 1)
    assert_array_equal(h['dims'], [5, 4, 3, 2])
    assert_almost_equal(h['tr'], 0.0)
    assert_almost_equal(h['flip_angle'], 0.0)
    assert_almost_equal(h['te'], 0.0)
    assert_almost_equal(h['ti'], 0.0)
    assert_almost_equal(h['fov'], 0.0)
    assert_array_almost_equal(h.get_vox2ras(), v2r)
    # data
    assert_almost_equal(dat, v, 7)


def test_write_noaffine_mgh():
    # now just save the image without the vox2ras transform
    # and see if it uses the default values to save
    v = np.ones((7, 13, 3, 22)).astype(np.uint8)
    # form a MGHImage object using data
    # and the default affine matrix (Note the "None")
    img = MGHImage(v, None)
    with InTemporaryDirectory():
        save(img, 'tmpsave.mgz')
        # read from the tmp file and see if it checks out
        mgz = load('tmpsave.mgz')
        h = mgz.header
        # Delete loaded image to allow file deletion by windows
        del mgz
    # header
    assert_equal(h['version'], 1)
    assert_equal(h['type'], 0)  # uint8 for mgh
    assert_equal(h['dof'], 0)
    assert_equal(h['goodRASFlag'], 1)
    assert_array_equal(h['dims'], [7, 13, 3, 22])
    assert_almost_equal(h['tr'], 0.0)
    assert_almost_equal(h['flip_angle'], 0.0)
    assert_almost_equal(h['te'], 0.0)
    assert_almost_equal(h['ti'], 0.0)
    assert_almost_equal(h['fov'], 0.0)
    # important part -- whether default affine info is stored
    assert_array_almost_equal(h['Mdc'], [[-1, 0, 0], [0, 0, 1], [0, -1, 0]])
    assert_array_almost_equal(h['Pxyz_c'], [0, 0, 0])


def bad_dtype_mgh():
    ''' This function raises an MGHError exception because
    uint16 is not a valid MGH datatype.
    '''
    # try to write an unsigned short and make sure it
    # raises MGHError
    v = np.ones((7, 13, 3, 22)).astype(np.uint16)
    # form a MGHImage object using data
    # and the default affine matrix (Note the "None")
    MGHImage(v, None)


def test_bad_dtype_mgh():
    # Now test the above function
    assert_raises(MGHError, bad_dtype_mgh)


def test_filename_exts():
    # Test acceptable filename extensions
    v = np.ones((7, 13, 3, 22)).astype(np.uint8)
    # form a MGHImage object using data
    # and the default affine matrix (Note the "None")
    img = MGHImage(v, None)
    # Check if these extensions allow round trip
    for ext in ('.mgh', '.mgz'):
        with InTemporaryDirectory():
            fname = 'tmpname' + ext
            save(img, fname)
            # read from the tmp file and see if it checks out
            img_back = load(fname)
            assert_array_equal(img_back.get_data(), v)
            del img_back


def _mgh_rt(img, fobj):
    file_map = {'image': FileHolder(fileobj=fobj)}
    img.to_file_map(file_map)
    return MGHImage.from_file_map(file_map)


def test_header_updating():
    # Don't update the header information if the affine doesn't change.
    # Luckily the test.mgz dataset had a bad set of cosine vectors, so these
    # will be changed if the affine gets updated
    mgz = load(MGZ_FNAME)
    hdr = mgz.header
    # Test against mri_info output
    exp_aff = np.loadtxt(io.BytesIO(b"""
    1.0000   2.0000   3.0000   -13.0000
    2.0000   3.0000   1.0000   -11.5000
    3.0000   1.0000   2.0000   -11.5000
    0.0000   0.0000   0.0000     1.0000"""))
    assert_almost_equal(mgz.affine, exp_aff, 6)
    assert_almost_equal(hdr.get_affine(), exp_aff, 6)
    # Test that initial wonky header elements have not changed
    assert_equal(hdr['delta'], 1)
    assert_almost_equal(hdr['Mdc'].T, exp_aff[:3, :3])
    # Save, reload, same thing
    img_fobj = io.BytesIO()
    mgz2 = _mgh_rt(mgz, img_fobj)
    hdr2 = mgz2.header
    assert_almost_equal(hdr2.get_affine(), exp_aff, 6)
    assert_equal(hdr2['delta'], 1)
    # Change affine, change underlying header info
    exp_aff_d = exp_aff.copy()
    exp_aff_d[0, -1] = -14
    # This will (probably) become part of the official API
    mgz2._affine[:] = exp_aff_d
    mgz2.update_header()
    assert_almost_equal(hdr2.get_affine(), exp_aff_d, 6)
    RZS = exp_aff_d[:3, :3]
    assert_almost_equal(hdr2['delta'], np.sqrt(np.sum(RZS ** 2, axis=0)))
    assert_almost_equal(hdr2['Mdc'].T, RZS / hdr2['delta'])


def test_cosine_order():
    # Test we are interpreting the cosine order right
    data = np.arange(60).reshape((3, 4, 5)).astype(np.int32)
    aff = np.diag([2., 3, 4, 1])
    aff[0] = [2, 1, 0, 10]
    img = MGHImage(data, aff)
    assert_almost_equal(img.affine, aff, 6)
    img_fobj = io.BytesIO()
    img2 = _mgh_rt(img, img_fobj)
    hdr2 = img2.header
    RZS = aff[:3, :3]
    zooms = np.sqrt(np.sum(RZS ** 2, axis=0))
    assert_almost_equal(hdr2['Mdc'].T, RZS / zooms)
    assert_almost_equal(hdr2['delta'], zooms)


def test_eq():
    # Test headers compare properly
    hdr = MGHHeader()
    hdr2 = MGHHeader()
    assert_equal(hdr, hdr2)
    hdr.set_data_shape((2, 3, 4))
    assert_false(hdr == hdr2)
    hdr2.set_data_shape((2, 3, 4))
    assert_equal(hdr, hdr2)


def test_header_slope_inter():
    # Test placeholder slope / inter method
    hdr = MGHHeader()
    assert_equal(hdr.get_slope_inter(), (None, None))


def test_mgh_load_fileobj():
    # Checks the filename gets passed to array proxy
    #
    # This is a bit of an implementation detail, but the test is to make sure
    # that we aren't passing ImageOpener objects to the array proxy, as these
    # were confusing mmap on Python 3.  If there's some sensible reason not to
    # pass the filename to the array proxy, please feel free to change this
    # test.
    img = MGHImage.load(MGZ_FNAME)
    assert_equal(img.dataobj.file_like, MGZ_FNAME)
    # Check fileobj also passed into dataobj
    with ImageOpener(MGZ_FNAME) as fobj:
        contents = fobj.read()
    bio = io.BytesIO(contents)
    fm = MGHImage.make_file_map(mapping=dict(image=bio))
    img2 = MGHImage.from_file_map(fm)
    assert_true(img2.dataobj.file_like is bio)
    assert_array_equal(img.get_data(), img2.get_data())


def test_mgh_reject_little_endian():
    bblock = b'\x00' * MGHHeader.template_dtype.itemsize
    with assert_raises(ValueError):
        MGHHeader(bblock, endianness='<')


def test_mgh_affine_default():
    hdr = MGHHeader()
    hdr['goodRASFlag'] = 0
    hdr2 = MGHHeader(hdr.binaryblock)
    assert_equal(hdr2['goodRASFlag'], 1)
    assert_array_equal(hdr['Mdc'], hdr2['Mdc'])
    assert_array_equal(hdr['Pxyz_c'], hdr2['Pxyz_c'])


def test_mgh_set_data_shape():
    hdr = MGHHeader()
    hdr.set_data_shape((5,))
    assert_array_equal(hdr.get_data_shape(), (5, 1, 1))
    hdr.set_data_shape((5, 4))
    assert_array_equal(hdr.get_data_shape(), (5, 4, 1))
    hdr.set_data_shape((5, 4, 3))
    assert_array_equal(hdr.get_data_shape(), (5, 4, 3))
    hdr.set_data_shape((5, 4, 3, 2))
    assert_array_equal(hdr.get_data_shape(), (5, 4, 3, 2))
    with assert_raises(ValueError):
        hdr.set_data_shape((5, 4, 3, 2, 1))


class TestMGHImage(tsi.TestSpatialImage, tsi.MmapImageMixin):
    """ Apply general image tests to MGHImage
    """
    image_class = MGHImage
    can_save = True

    def check_dtypes(self, expected, actual):
        # Some images will want dtypes to be equal including endianness,
        # others may only require the same type
        # MGH requires the actual to be a big endian version of expected
        assert_equal(expected.newbyteorder('>'), actual)
