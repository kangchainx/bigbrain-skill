# Bigbrain README demo. Render from the repo root:
#   vhs docs/demo.tape
# Offline: docs/demo.sh drives the real CLI against scripts/mock_server.py.

Output docs/demo.gif
Output docs/demo.mp4

Require python3

Set Shell "bash"
Set FontSize 18
Set Width 1200
Set Height 860
Set Padding 24
Set LineHeight 1.2
Set Theme "Catppuccin Mocha"
Set TypingSpeed 45ms
Set Framerate 15
Set PlaybackSpeed 1.0

Hide
Type "export PS1='$ ' DEMO_PAUSE=1.3 && clear"
Enter
Show

Sleep 600ms
Type "bash docs/demo.sh"
Sleep 400ms
Enter
# demo.sh runs ~11s with DEMO_PAUSE=1.3; hold the final frame for a few seconds.
Sleep 17s
