# Third-party software in Litwell

Litwell is licensed under the Apache License 2.0 (see LICENSE). The downloadable
apps also contain the software below, each under its own licence. All of these
licences allow redistribution inside an Apache-2.0 application; none requires
Litwell itself to be released under a different licence.

| Component | Version checked | Licence | Notes |
|---|---|---|---|
| Python (and Tcl/Tk) | 3.12 | PSF License; Tcl/Tk BSD-style | The interpreter and GUI toolkit inside the app. |
| requests | 2.34 | Apache-2.0 | Its NOTICE: "Requests, Copyright 2019 Kenneth Reitz". |
| urllib3 | 1.26 | MIT | |
| certifi | 2026.7 | MPL-2.0 | File-level licence. Litwell ships certifi's `cacert.pem` unmodified; the MPL-2.0 text is at https://www.mozilla.org/MPL/2.0/ and the source is the certifi package. |
| charset-normalizer | 3.5 | MIT | |
| idna | 3.19 | BSD-3-Clause | Keep the copyright notice and licence text. |
| openpyxl | 3.1 | MIT | |
| et_xmlfile | 2.0 | MIT | Used by openpyxl. |

Build-time only (used to make the apps, not shipped as separate code):

| Component | Licence | Notes |
|---|---|---|
| PyInstaller | GPL-2.0-or-later with a special exception | The exception explicitly lets an application built with PyInstaller be distributed under any licence, so the apps are not GPL. PyInstaller's bootloader is the part that ends up inside the app. |
| altgraph, macholib, pyinstaller-hooks-contrib, packaging, setuptools | MIT / Apache-2.0 / BSD | Build tooling. |

Licences were read from each package's own metadata on the build machine
(`importlib.metadata`). Check them again when a dependency is upgraded.
