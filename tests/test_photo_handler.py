"""IF-2 — the photo handler downloads, confirms, and cleans up after itself."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from pantrypulse.interface.handlers.commands import MAIN_KEYBOARD
from pantrypulse.interface.handlers.photos import photo


def _make_update(*, has_photo: bool = True):
    """A fake Update carrying one PhotoSize whose get_file() returns a fake
    File that "downloads" by writing real bytes to the destination path."""
    update = MagicMock()
    update.effective_chat.id = 12345
    update.effective_chat.send_message = AsyncMock()

    if not has_photo:
        update.message.photo = []
        return update

    fake_file = MagicMock()
    fake_file.file_id = "FILEID123"

    async def fake_download(destination: Path):
        Path(destination).write_bytes(b"x" * 2048)  # pretend it's a 2KB photo

    fake_file.download_to_drive = AsyncMock(side_effect=fake_download)

    photo_size = MagicMock()
    photo_size.get_file = AsyncMock(return_value=fake_file)

    update.message.photo = [photo_size]  # Telegram lists smallest -> largest
    return update


def _context():
    """A context whose user_data is a real dict, as PTB provides.

    A MagicMock user_data answers .get()/.pop() with a truthy mock, which the
    handler correctly reads as "this chat was in demo mode".
    """
    context = MagicMock()
    context.user_data = {}
    return context


@pytest.mark.asyncio
async def test_photo_round_trips_and_confirms_receipt():
    update = _make_update()
    await photo(update, context=_context())

    update.effective_chat.send_message.assert_awaited_once()
    call = update.effective_chat.send_message.call_args
    assert "Photo received" in call.args[0]
    assert "2 KB" in call.args[0]
    assert "not read or saved" in call.args[0]
    assert call.kwargs["reply_markup"] is MAIN_KEYBOARD


@pytest.mark.asyncio
async def test_downloaded_photo_is_deleted_after_replying():
    """Temp storage means temp: nothing from a photo should outlive the handler."""
    captured_path = {}
    update = _make_update()

    original_download = update.message.photo[0].get_file

    async def get_file_and_capture():
        file = await original_download()

        async def download_and_track(destination: Path):
            captured_path["path"] = Path(destination)
            Path(destination).write_bytes(b"x" * 1024)

        file.download_to_drive = AsyncMock(side_effect=download_and_track)
        return file

    update.message.photo[0].get_file = get_file_and_capture

    await photo(update, context=_context())

    assert "path" in captured_path
    assert not captured_path["path"].exists()


@pytest.mark.asyncio
async def test_non_photo_message_is_ignored():
    update = _make_update(has_photo=False)
    await photo(update, context=_context())
    update.effective_chat.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_missing_chat_does_not_raise():
    update = _make_update()
    update.effective_chat = None
    await photo(update, context=_context())  # must not raise
