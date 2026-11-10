"""Qt Multimedia playback and stop check for the Windows spike."""

from PySide6.QtCore import QEventLoop, QTimer, QUrl
from PySide6.QtMultimedia import QAudioOutput, QMediaDevices, QMediaPlayer
from PySide6.QtWidgets import QApplication, QLabel


def check_playback(paths):
    app = QApplication.instance() or QApplication([])
    window = QLabel("NoteFlow M0\n正在验证 WAV 播放与停止…")
    window.setWindowTitle("NoteFlow M0")
    window.resize(320, 100)
    window.show()

    player = QMediaPlayer()
    audio = QAudioOutput()
    audio.setVolume(0.15)
    player.setAudioOutput(audio)
    results = {}
    for path in paths:
        loop = QEventLoop()
        timeout = QTimer()
        timeout.setSingleShot(True)
        result = {"ok": False, "detail": "播放位置未在 10 秒内前进"}

        def on_position(position):
            if position < 250 or player.playbackState() != QMediaPlayer.PlaybackState.PlayingState:
                return
            result["position_ms"] = position
            loop.quit()

        def on_error(_error, message):
            result["detail"] = message
            loop.quit()

        player.positionChanged.connect(on_position)
        player.errorOccurred.connect(on_error)
        timeout.timeout.connect(loop.quit)
        timeout.start(10000)
        player.setSource(QUrl.fromLocalFile(str(path)))
        if player.error() == QMediaPlayer.Error.NoError:
            player.play()
            if player.error() == QMediaPlayer.Error.NoError and "position_ms" not in result:
                loop.exec()
        timeout.stop()
        player.positionChanged.disconnect(on_position)
        player.errorOccurred.disconnect(on_error)
        player.stop()
        player.setSource(QUrl())
        if "position_ms" in result:
            result["ok"] = (
                player.playbackState() == QMediaPlayer.PlaybackState.StoppedState
                and player.position() == 0 and player.source().isEmpty()
            )
            result["detail"] = "已停止并释放来源" if result["ok"] else "停止状态或来源重置失败"
        results[path.stem] = result

    window.close()
    app.processEvents()
    return {"output_devices": len(QMediaDevices.audioOutputs()), "files": results}
