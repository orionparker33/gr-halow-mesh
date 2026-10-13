# SPDX-License-Identifier: GPL-3.0-or-later
"""Small public PHY checks; private over-air vectors are verified separately."""

import unittest

import numpy as np

from halow_mesh import phy


class PhyChecks(unittest.TestCase):
    def test_fcs_gate(self):
        frame=b"123456789"+(0xcbf43926).to_bytes(4,"little")
        self.assertTrue(phy._fcs_ok(frame))
        self.assertFalse(phy._fcs_ok(frame[:-1]+b"\x00"))

    def test_constellation_labeling(self):
        for name in ("BPSK","QPSK","16QAM","64QAM","256QAM"):
            symbols=phy._constellation(name)
            nbits=int(np.log2(len(symbols)))
            soft=phy._soft_demap(symbols,name).reshape(-1,nbits)
            decoded=(soft>0).astype(np.uint8)
            expected=np.array([[(k>>(nbits-j-1))&1 for j in range(nbits)]
                               for k in range(len(symbols))],dtype=np.uint8)
            np.testing.assert_array_equal(decoded,expected)

    def test_noise_has_no_mpdu(self):
        rng=np.random.default_rng(20261013)
        noise=(rng.normal(size=16000)+1j*rng.normal(size=16000)).astype(np.complex64)
        self.assertEqual(phy.detect_stf_raw(noise,8e6),[])
        self.assertEqual(phy.decode_iq_window(noise,8e6,8),[])
        self.assertEqual(phy.decode_iq_window(noise,8e6,1),[])

    def test_width_and_nyquist(self):
        samples=np.zeros(16000,dtype=np.complex64)
        with self.assertRaises(ValueError):
            phy.decode_iq_window(samples,8e6,16)
        with self.assertRaises(ValueError):
            phy.decode_iq_window(samples,8e6,8,1e6)

    def test_sig_tail_gate(self):
        # A CRC-valid header with a nonzero BCC termination tail must not
        # trigger a costly payload decode or produce an MPDU.
        bits = np.zeros(48, dtype=np.uint8)
        length = 30
        for j in range(9):
            bits[25+j] = (length >> j) & 1
        crc = phy._crc4(bits[:38])
        for j in range(4):
            bits[38+j] = (crc >> (3-j)) & 1
        self.assertEqual(phy._parse_sig(bits, 2)["length"], 30)
        bits[47] = 1
        with self.assertRaises(phy.PhyReject):
            phy._parse_sig(bits, 2)


if __name__=="__main__":
    unittest.main()
