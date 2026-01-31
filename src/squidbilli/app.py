from squidbilli.transport import Transport
from squidbilli.mixer_state import MixerState
from squidbilli.stems import StemManager
from squidbilli.ui import UI
from squidbilli.clips import ClipManager
from squidbilli.audio_process import AudioController
from squidbilli.ingest_service.process import IngestController


def main():
    print("Initializing DJ Stem Mixer...")

    transport_a = Transport()
    transport_b = Transport()
    mixer_state = MixerState()

    clip_manager_a = ClipManager()
    clip_manager_b = ClipManager()
    stem_manager_a = StemManager(clip_manager=clip_manager_a)
    stem_manager_b = StemManager(clip_manager=clip_manager_b)

    audio = AudioController()
    audio.start()

    ingest = IngestController()
    ingest.start()

    ui = UI(transport_a, transport_b, mixer_state, stem_manager_a, stem_manager_b, audio, ingest)

    try:
        ui.setup()
        ui.run()
    except KeyboardInterrupt:
        pass
    finally:
        print("Shutting down...")
        audio.stop()
        ingest.stop()


if __name__ == "__main__":
    main()
