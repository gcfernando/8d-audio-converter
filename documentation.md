---
layout: default
title: "Audio8D — Documentation and Guides"
description: "FFmpeg-based 8D audio converter for Windows and Linux, with desktop and command-line interfaces."
permalink: /documentation/
---

# Audio8D Documentation

Find the GUI walkthrough, CLI examples, audio-processing details and packaging instructions for the Python/FFmpeg 8D audio converter.

<a id="explore-more"></a>
<a id="markdown-source-library"></a>
<a id="read-online"></a>

## 🧭 Choose a guide

| Task | Guide |
|---|---|
| Download and check a package | [Quick start](README.md#quick-start) and [system checks](README.md#check-that-it-works) |
| Convert a first song in the GUI | [Window walkthrough](README.md#your-first-song-the-window) |
| Automate batches and per-song settings | [Command-line reference](README.md#command-line) |
| Tune styles, loudness and local storage | [Configuration and reference](README.md#reference) |
| Understand the conversion stages | [Processing architecture](README.md#how-it-works) |
| Develop or build portable packages | [Source setup](README.md#running-from-source), [packaging](README.md#building-the-packages) and [tests](README.md#tests-and-project-layout) |
| Diagnose platform or audio limitations | [Troubleshooting](README.md#troubleshooting) and [known limitations](README.md#known-limitations) |
| Review bundled-software licensing | [Third-party notices](THIRD-PARTY-NOTICES.md) and [MIT license](LICENSE) |

## 🔗 Source references

[Package metadata and optional dependencies](pyproject.toml) · [Pipeline implementation](src/pipeline.py) · [CLI option definitions](src/options.py) · [Build entry point](packaging/build_release.py)

The README is the application's full user guide, also linked from its Help action. This index routes readers to that guide rather than maintaining a second copy of CLI options.

## 🌐 Published documentation

This index is also rendered by the repository's GitHub Pages site. Relative links above point to the authored repository documents. The standalone ZIPs
contain a README snapshot from their build; source documentation changes do not update
those archives. The app's **Open the full guide** action opens the online README.

## 🧪 Reading and verification boundaries

The [processing guide](README.md#how-it-works) explains publication before the optional
quality check, cache identity and shared GUI/CLI settings. The [build guide](README.md#building-the-packages)
records the current archive contents and the missing first-party license notice.
The [known limitations](README.md#known-limitations) distinguish approximate spatial
and preview behavior from measured output. For a focused, conversion-free check of
CLI examples, run `python -m pytest tests/unit/test_readme_commands.py` from the
repository after installing the development dependencies.

[Repository](https://github.com/gcfernando/audio-8d) · [Project overview](README.md)
