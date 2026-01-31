# DJ Stem Mixer

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
