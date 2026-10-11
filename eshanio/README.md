# Eshanio system (separate project)

The `hf_video_platform` directory contains the separate HFVideoPlatform project
from `C:\Users\Eshan\Desktop\eshanio`. It is kept independent of the live
streaming app in the repository root; neither app's source files were merged.

The root Hugging Face Docker Space continues to launch the streaming app. It
also starts the nested Node M3U API and video catalog API as internal services;
the root app proxies the M3U panel and video requests through port 7860. The
desktop platform still has its own launcher and services.

To run the desktop platform locally, use its own build and launch scripts inside
`hf_video_platform`. Generated builds and installed dependencies are not copied,
so install the required tools and build it before launching.

Local account data, signing certificates, executables, dependency folders, and
environment files are excluded here. Add any required account data or signing
certificate locally; do not commit secrets.
