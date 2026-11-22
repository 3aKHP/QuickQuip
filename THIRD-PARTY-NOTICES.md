# Third-Party Notices

QuickQuip source code is licensed under [WTFPL v2](LICENSE). Prebuilt release
artifacts (such as Docker images and Windows packages) bundle third-party
Python dependencies installed from `requirements.txt`. The following copyleft
components are included in binary or package distributions:

## pilk-nogil (0.4.3)

- **License**: GNU General Public License v3.0 (GPL-3.0)
- **Upstream repository**: https://github.com/MelodyYuuka/pilk-nogil
- **PyPI release & source distribution**: https://pypi.org/project/pilk-nogil/0.4.3/
- **Underlying codec**: Based on Skype SILK SDK (BSD-3-Clause) and `silk-v3-decoder`.
- **Usage in QuickQuip**: Invoked inside an isolated subprocess (`quickquip.generation.audio_worker`) to decode raw SILK v3 voice messages into WAV for ASR.

## lunardate

- **License**: GNU General Public License v3.0 or later (GPL-3.0-or-later)
- **Upstream repository**: https://github.com/lidaobing/python-lunardate
- **PyPI release & source distribution**: https://pypi.org/project/lunardate/
- **Usage in QuickQuip**: Pure-Python Chinese lunar calendar date calculation in `quickquip.chat.festival`.
