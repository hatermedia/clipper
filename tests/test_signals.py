from clipper.detect.signals import WindowSignal


def make_signal(**kwargs) -> WindowSignal:
    base = dict(start=0.0, end=10.0)
    base.update(kwargs)
    return WindowSignal(**base)


def test_laugh_and_jerk_qualify_without_words() -> None:
    signal = make_signal(laugh=0.84, jerk=0.92, peak_time=4.0)
    assert signal.agreement()
    assert signal.reason() == "[laugh 0.84, jerk 0.92]"


def test_loud_and_jerk_do_not_qualify_alone() -> None:
    signal = make_signal(loud=0.95, jerk=0.95, peak_time=4.0)
    assert not signal.agreement()


def test_three_signals_and_jerk_qualify_for_flat_quote() -> None:
    signal = make_signal(
        jerk=0.90,
        loud=0.80,
        pitch=0.90,
        pitch_ratio=1.8,
        quote="because there's no one here",
    )
    assert signal.agreement()


def test_tactical_callout_is_rejected() -> None:
    signal = make_signal(
        laugh=0.80,
        jerk=0.90,
        quote="enemy remaining, reloading B site",
    )
    assert not signal.agreement()


def test_laugh_and_fast_without_jerk_or_loud_is_rejected() -> None:
    signal = make_signal(laugh=0.80, fast=0.90, wps=7.0, quote="")
    assert not signal.agreement()


def test_one_word_quote_needs_laughter() -> None:
    flat = make_signal(jerk=0.90, fast=0.90, wps=6.0, quote="Yeah.")
    assert not flat.agreement()
    laugh = make_signal(jerk=0.90, laugh=0.80, quote="Stop.")
    assert laugh.agreement()
    assert laugh.reason() == "[laugh 0.80, jerk 0.90]"
