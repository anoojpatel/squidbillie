<h1 align="center">DJ Stem Mixer</h1>
<img width="1778" height="1401" alt="Screenshot 2026-01-31 at 2 42 23 PM" src="https://github.com/user-attachments/assets/f10e985b-59d6-4642-b975-0c5e848cc311" />

A macOS-first Python prototype for a “DJ stem mixer + Octotrack-style clip launcher + live-coding param control”.

## Setup

1.  **Install System Dependencies:**
    You need `ffmpeg` installed.
    ```bash
    brew install ffmpeg
    ```

2.  **Install Python Dependencies:**
    ```bash
    uv sync
    ```

3.  **Run:**
    ```bash
    uv run squidbilli
    # or
    uv run python -m squidbilli
    ```

## Usage

1.  **Load Track:** Click "Load Track" to open an MP3/WAV file.
2.  **Play:** Press Space or click Play to start the full mix.
3.  **Split:** Click "Separate Stems" to begin background stem separation.
4.  **Mix:** Use the 8-lane mixer to control volumes, mutes, solos, and filters.
5.  **Perform:** Trigger clips in the grid (when implemented) or live-code parameters.

## Key Bindings

-   **Space:** Play/Pause
-   **1-8:** Mute Lane
-   **Shift + 1-8:** Solo Lane
-   **[ / ]:** Nudge Tempo
-   **Enter:** Quantized Scene Launch

## Architecture

-   **UI:** DearPyGui
-   **Audio:** sounddevice (PortAudio) + numpy ring buffers
-   **Stems:** Demucs (via subprocess)
-   **FX:** Pedalboard / Custom DSP

## Features
<img width="1778" height="1401" alt="Screenshot 2026-01-31 at 2 43 00 PM" src="https://github.com/user-attachments/assets/d388d873-a0bd-47d8-a8e8-44752ffbde66" />

- Automatic Stem-splitter using PyDSP into 8 Channels (Kick, Snare/Clap, Hats, Percs/Top, Bass, Chords, Lead, Vox)
- Tidal-like pattern systems for 1-8 per Stem lane
- Mixer Scenes that allow you to store Mixer states and Linearly Interpolate ("Morph") between 8 parameters across all 8 channels for both Scenes
- CLip Grid creates rolling clips from a given song and use an OctoTrack-like Scene system
    - Clips are a 32-bar "Page" and Roll to the next 32 bar if "Follow" is selected. 
- CDJ-like Mixer with controls for every Stem lane
- Waveform Highlights outlining where clips are grabbed from
- Upload Songs directly from SoundCloud Links
- Record every action into a JSON Format, as well as generating Tutroials
- Leverage an Audiotool-like Heisenberg Phase-Oscillating Synthesizer
