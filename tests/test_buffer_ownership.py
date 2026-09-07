from __future__ import annotations

from ocring.ocr.buffer_ownership import BufferOwnership, OwnershipState


def test_buffer_ownership_tracks_reference_count_and_releaseable_state() -> None:
    ownership = BufferOwnership("frame-1")

    ownership.transition(OwnershipState.BUFFERED)
    ownership.acquire()
    assert ownership.reference_count == 2

    ownership.transition(OwnershipState.RESOLVED)
    ownership.release()
    ownership.release()

    assert ownership.reference_count == 0
    assert ownership.state is OwnershipState.RELEASEABLE

