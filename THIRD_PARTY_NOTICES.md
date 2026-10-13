# Third-party notices

Portions of `python/halow_mesh/phy.py` are adapted from Daniel Estévez's
[IEEE 802.11ah analysis notebook](https://github.com/daniestevez/jupyter_notebooks/tree/master/IEEE_802.11ah),
including the 2 MHz training sequences, pilot sequence, synchronization,
interleaver, convolutional decoder, scrambler, and FCS algorithms. His
[repository](https://github.com/daniestevez/jupyter_notebooks) licenses source
code under the MIT License. The 4/8 MHz receiver, bounded GNU Radio block,
and integration are Atlas work.

The MIT License permission notice for the adapted software follows:

> Permission is hereby granted, free of charge, to any person obtaining a
> copy of this software and associated documentation files (the "Software"),
> to deal in the Software without restriction, including without limitation
> the rights to use, copy, modify, merge, publish, distribute, sublicense,
> and/or sell copies of the Software, and to permit persons to whom the
> Software is furnished to do so, subject to the following conditions:
>
> The above copyright notice and this permission notice shall be included in
> all copies or substantial portions of the Software.
>
> THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
> IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
> FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
> AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
> LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
> FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS
> IN THE SOFTWARE.

The 1 MHz LTF and SIG repetition/interleaver constants in `phy.py` were
cross-checked against the GPL-3.0-or-later
[gr-ieee802-11ah](https://github.com/irongiant33/gr-ieee802-11ah) source.
The repository's copyright notices credit Bastian Bloessl and its
contributors. This project's GPL-3.0-or-later license is compatible with
those source terms.
