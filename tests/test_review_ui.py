from __future__ import annotations

import json
from pathlib import Path

from ocring.ocr.review import ReviewRecord, ReviewSession, ReviewStatus, load_review_session_from_store
from ocring.ui.record_card import review_item_display_name
from ocring.ui.review_window import ReviewWindow


def _sample_report() -> dict[str, object]:
    return {
        "frame_reports": [
            {
                "frame": {
                    "session_id": "review-session-001",
                }
            }
        ],
        "assembled_records": [
            {
                "row_slot": 1,
                "fields": {
                    "item_name": "Power Bore",
                    "item_rarity": "Tier IV",
                    "item_type": "Rocket Launcher",
                    "item_count": "2",
                },
                "field_details": {
                    "item_name": {
                        "evidence_source": "row_list",
                        "evidence": [{"raw_ocr": "Power Bore"}],
                    },
                    "item_type": {
                        "evidence_source": "detail_panel",
                        "evidence": [{"raw_ocr": "Rocket Launcher"}],
                    },
                },
                "support_summary": {
                    "item_name": {"source_crop_ids": ["c1"]},
                },
                "source_frame_ids": ["f1", "f2"],
                "source_row_ids": ["f1:row:1", "f2:row:1"],
                "overlap_provenance": {"overlaps": []},
                "reasons": [],
            },
            {
                "row_slot": 2,
                "fields": {
                    "item_name": "Hellbug Rocket",
                    "item_rarity": "Tier III",
                    "item_type": "Shotgun",
                    "item_count": "1",
                },
                "field_details": {},
                "support_summary": {},
                "source_frame_ids": ["f2"],
                "source_row_ids": ["f2:row:2"],
                "overlap_provenance": {},
                "reasons": [],
            },
        ],
    }


def test_review_session_initializes_from_report() -> None:
    session = ReviewSession.from_report(_sample_report())

    assert session.session_id == "review-session-001"
    assert len(session.records) == 2
    assert session.records[0].review_status == ReviewStatus.PENDING
    assert session.records[0].field_details["item_type"]["evidence_source"] == "detail_panel"
    assert session.get_pending_count() == 2


def test_unknown_review_record_displays_as_unresolved_exception() -> None:
    record = ReviewRecord(
        record_id="unknown-1",
        row_slot=1,
        fields={"item_name": "UNKNOWN"},
        support_summary={},
        source_frame_ids=[],
        source_row_ids=[],
        overlap_provenance={},
        reasons=["IDENTITY_HELD"],
    )

    assert review_item_display_name(record) == "Unresolved item"
    assert record.fields["item_name"] == "UNKNOWN"


def test_accept_reject_and_correct_update_state() -> None:
    session = ReviewSession.from_report(_sample_report())

    session.accept_record("record-001")
    session.reject_record("record-002")
    session.correct_field("record-001", "item_name", "Corrected Bore")

    assert session.records[0].review_status == ReviewStatus.CORRECTED
    assert session.records[0].fields["item_name"] == "Corrected Bore"
    assert session.records[1].review_status == ReviewStatus.REJECTED
    assert session.corrections["record-001"]["item_name"] == "Corrected Bore"


def test_get_committable_records_returns_only_accepted_and_corrected() -> None:
    session = ReviewSession.from_report(_sample_report())

    session.accept_record("record-001")
    session.reject_record("record-002")

    committable = session.get_committable_records()

    assert [record.record_id for record in committable] == ["record-001"]


def test_ui_loads_without_crashing(tmp_path: Path) -> None:
    class FakeWidget:
        def __init__(self, *args, **kwargs) -> None:
            self._children: list[FakeWidget] = []
            self._selection: tuple[int, ...] = ()
            self._text = ""
            self._title = ""

        def grid(self, *args, **kwargs) -> None:
            return None

        def pack(self, *args, **kwargs) -> None:
            return None

        def bind(self, *args, **kwargs) -> None:
            return None

        def insert(self, *args, **kwargs) -> None:
            return None

        def delete(self, *args, **kwargs) -> None:
            return None

        def selection_set(self, index: int) -> None:
            self._selection = (index,)

        def selection_clear(self, *args, **kwargs) -> None:
            self._selection = ()

        def curselection(self) -> tuple[int, ...]:
            return self._selection

        def configure(self, *args, **kwargs) -> None:
            return None

        config = configure

        def columnconfigure(self, *args, **kwargs) -> None:
            return None

        def rowconfigure(self, *args, **kwargs) -> None:
            return None

        def title(self, value: str) -> None:
            self._title = value

        def geometry(self, *args, **kwargs) -> None:
            return None

        def mainloop(self) -> None:
            return None

        def after(self, _delay: int, callback) -> None:
            callback()

        def winfo_children(self) -> list["FakeWidget"]:
            return self._children

        def destroy(self) -> None:
            return None

        def set_record(self, *args, **kwargs) -> None:
            return None

    class FakeTkModule:
        END = "end"
        Misc = object
        TclError = Exception
        PhotoImage = FakeWidget
        StringVar = lambda *args, value="", **kwargs: type("Var", (), {"set": lambda self, v: None})()
        Label = FakeWidget
        Text = FakeWidget
        Listbox = FakeWidget
        Tk = FakeWidget

    class FakeTtkModule:
        Frame = FakeWidget
        Label = FakeWidget
        Button = FakeWidget

    from ocring.ui import review_window as review_window_module

    review_window_module.tk = FakeTkModule
    review_window_module.ttk = FakeTtkModule
    review_window_module.messagebox = type("MB", (), {"showinfo": staticmethod(lambda *args, **kwargs: None)})
    review_window_module.simpledialog = type("SD", (), {"askstring": staticmethod(lambda *args, **kwargs: None)})
    review_window_module.RecordCard = FakeWidget
    review_window_module.EvidenceViewer = FakeWidget

    session = ReviewSession.from_report(_sample_report())
    window = ReviewWindow(session, sessions_root=tmp_path, master=FakeWidget())

    assert window.review_session.session_id == "review-session-001"


def test_load_review_session_from_store_uses_latest_commit(tmp_path: Path) -> None:
    sessions_root = tmp_path / "sessions"
    session_root = sessions_root / "review-session-001"
    older = session_root / "20260101T000000000000Z-old"
    newer = session_root / "20260101T000000000001Z-new"
    older.mkdir(parents=True)
    newer.mkdir(parents=True)
    (older / "report.json").write_text(json.dumps({"frame_reports": [{"frame": {"session_id": "old"}}], "assembled_records": []}), encoding="utf-8")
    (newer / "report.json").write_text(json.dumps(_sample_report()), encoding="utf-8")

    session = load_review_session_from_store("review-session-001", sessions_root=sessions_root)

    assert session.session_id == "review-session-001"
    assert len(session.records) == 2
