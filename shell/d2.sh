# diablo2-overlay shell helpers.
#
# Source from ~/.bashrc:
#     source ~/diablo2-overlay/shell/d2.sh
#
#     d2_on            start the overlay (detached; survives closing the shell)
#     d2_off           stop it
#     d2_status        is it running
#     d2_outputs       list monitors (for [overlay].output in config.toml)
#     d2_calibrate     check what the OCR sees right now

# The checkout may be called either name.
D2_OVERLAY_DIR="${D2_OVERLAY_DIR:-$([ -d "$HOME/diablo2-ocular-assist" ] && echo "$HOME/diablo2-ocular-assist" || echo "$HOME/diablo2-overlay")}"

D2_OVERLAY_LOG="${D2_OVERLAY_LOG:-${XDG_RUNTIME_DIR:-/tmp}/diablo2-overlay.log}"

d2_on() {
    local overlay="$D2_OVERLAY_DIR/overlay.py"
    if [ ! -x "$overlay" ]; then
        echo "d2_on: $overlay not found or not executable" >&2
        return 1
    fi

    # overlay.py refuses to start a second instance, but check first so the
    # common case prints something useful instead of an error.
    if d2_status >/dev/null 2>&1; then
        echo "overlay already running (d2_off to stop it)"
        return 0
    fi

    # setsid detaches it from this terminal, so closing the shell -- or the
    # shell dying -- does not take the overlay down mid-match.
    setsid "$overlay" "$@" >"$D2_OVERLAY_LOG" 2>&1 </dev/null &
    disown 2>/dev/null

    # Give it a moment, then report honestly rather than assuming it worked.
    local i
    for i in 1 2 3 4 5 6 7 8 9 10; do
        sleep 0.2
        if d2_status >/dev/null 2>&1; then
            echo "overlay on — settings window is open; closing it stops everything"
            return 0
        fi
    done

    echo "overlay failed to start; last output:" >&2
    tail -n 20 "$D2_OVERLAY_LOG" >&2
    return 1
}

d2_off() {
    if ! d2_status >/dev/null 2>&1; then
        echo "overlay not running"
        return 0
    fi
    "$D2_OVERLAY_DIR/overlay.py" --ctl quit >/dev/null 2>&1

    local i
    for i in 1 2 3 4 5; do
        sleep 0.2
        d2_status >/dev/null 2>&1 || { echo "overlay off"; return 0; }
    done

    # It ignored the quit command; make sure it is actually gone rather than
    # leaving a click-through window stuck on screen with no way to reach it.
    pkill -f "overlay\.py" 2>/dev/null
    sleep 0.3
    echo "overlay off (forced)"
}

d2_status() {
    # `overlay.py --ctl ...` invocations are short-lived processes that also
    # match the script path, so exclude them -- otherwise stopping the overlay
    # can briefly look like it is still running.
    # Match on the script name, not the full path: the overlay may have been
    # started as ./overlay.py or python3 overlay.py, and an absolute-path
    # pattern silently misses those -- which shows up as d2_on and
    # d2_status disagreeing about whether anything is running.
    if pgrep -af "overlay\.py" 2>/dev/null \
        | grep -v -- '--ctl' | grep -q .; then
        echo "overlay running"
        return 0
    fi
    echo "overlay not running"
    return 1
}

d2_calibrate() {
    "$D2_OVERLAY_DIR/tools/calibrate.py" "$@"
}

d2_outputs() {
    "$D2_OVERLAY_DIR/overlay.py" --list-outputs
}
