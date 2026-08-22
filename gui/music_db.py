"""data/others/music_db.xml -> Song objects, cross-referenced against data/music.

The db is declared "shift-jis" but is really cp932 (superset used by the
actual game data - straight shift-jis chokes on some artist names in it);
ElementTree's own encoding= only accepts encodings expat knows, and expat
does not know cp932, so the file is decoded by hand first and parsed as a
plain str - see the module-level `parse()` for the two-step reason.

Difficulty tags map onto the .vox filename suffix used throughout this
project (apply_chart.py, notes/convert.py):
    novice=1n  advanced=2a  exhaust=3e  infinite=4i  maximum=5m
A song carries at most one of {infinite, maximum} - never both - so the UI
only ever needs 4 "tiles": novice/advanced/exhaust/top, same as the game's
own song-select screen and the same as this game data's own jacket-file
convention (jk_<id>_1..4.png; a 5th image is never used even when the song
has `maximum` rather than `infinite`, since it reuses tile 4's slot).
"""
import os
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

DIFF_ORDER = ["novice", "advanced", "exhaust", "infinite", "maximum"]
DIFF_SUFFIX = {"novice": "1n", "advanced": "2a", "exhaust": "3e",
               "infinite": "4i", "maximum": "5m"}
DIFF_SHORT = {"novice": "NOV", "advanced": "ADV", "exhaust": "EXH",
              "infinite": "INF", "maximum": "MXM"}
# UI preview slot, 1..4 - always 4 boxes regardless of which top-tier tag a
# song carries (infinite XOR maximum, never both - see module docstring).
DIFF_TILE = {"novice": 1, "advanced": 2, "exhaust": 3, "infinite": 4, "maximum": 4}

# jk_<id>_<n>.png's own numbering, 1..5 - one slot per actual difficulty tag,
# NOT per UI slot. Confirmed against 2393_alive_dadadaizu (maximum, no
# infinite): it ships jk_2393_{1,2,3,5}.png and no jk_2393_4.png at all, so
# reusing DIFF_TILE's 1..4 (as an earlier version of this file did) silently
# picked the wrong file - and for a song with no jk_<id>_4/5 of its own,
# jacket_path()'s existing fallback to _1 still applies on top of this.
DIFF_JACKET_NUM = {"novice": 1, "advanced": 2, "exhaust": 3, "infinite": 4, "maximum": 5}

# info/version -> which SDVX release the song debuted in (the "Source" column)
VERSION_NAME = {
    1: "BOOTH", 2: "INFINITE INFECTION", 3: "GRAVITY WARS",
    4: "HEAVENLY HAVEN", 5: "VIVID WAVE", 6: "EXCEED GEAR",
    7: "NABLA"
}


@dataclass
class Difficulty:
    key: str            # "novice" | "advanced" | "exhaust" | "infinite" | "maximum"
    suffix: str          # "1n" .. "5m"
    difnum: int          # raw <difnum>: one implied decimal place, no decimal point - see level_display
    illustrator: str
    effected_by: str     # chart/effect author - ksh_format.md's "effect" field

    @property
    def level_display(self):
        """<difnum> is stored as the level with its decimal point removed
        (207 means 20.7), not a plain integer - dividing by 10 the naive way
        (int(difnum)) silently drops the fractional digit instead of raising,
        so this is spelled out here rather than left to the caller. A whole
        level (difnum a multiple of 10) drops the ".0" - "17", not "17.0"."""
        if self.difnum % 10 == 0:
            return str(self.difnum // 10)
        return "%.1f" % (self.difnum / 10.0)

    @property
    def level_int(self):
        """ksh_format.md's `level` field is an int, 1-20 - the decimal level
        has to collapse into that range for the .ksh header rather than
        writing something KSM won't accept. The UI shows level_display
        instead, uncapped and with its decimal intact.

        Rounds down, not to nearest: `round()` would send a difnum like 175
        (17.5, and not rare - 407 charts carry it) to 18 via Python's
        round-half-to-even, overstating the level by a full point. Truncating
        via integer division matches how SDVX's own level display treats a
        half-level - it's a "17" with a plus/star next to it, not a "17" or
        "18" depending on parity of the whole number (user-reported)."""
        return max(1, min(20, self.difnum // 10))


@dataclass
class Song:
    id: int
    folder: str                      # e.g. "0001_albida_muryoku"
    title: str
    artist: str
    ascii: str
    version: int                     # "Source" column
    distribution_date: str           # "YYYY-MM-DD" or "" if unset/zero
    genre: int
    difficulties: dict = field(default_factory=dict)   # key -> Difficulty

    @property
    def version_name(self):
        return VERSION_NAME.get(self.version, str(self.version))

    def top_difficulty(self):
        """The tile-4 difficulty: maximum if present, else infinite."""
        return self.difficulties.get("maximum") or self.difficulties.get("infinite")

    def tiles(self):
        """Up to 4 (tile_index, Difficulty) pairs, tile 4 being top_difficulty()."""
        out = {}
        for key in ("novice", "advanced", "exhaust"):
            d = self.difficulties.get(key)
            if d:
                out[DIFF_TILE[key]] = d
        top = self.top_difficulty()
        if top:
            out[4] = top
        return sorted(out.items())

    def jacket_path(self, music_dir, diff_key, fallback_music_dir=None):
        """Best-effort jacket path for a difficulty key - tries that
        difficulty's own jk_<id>_<DIFF_JACKET_NUM>.png first, falls back to
        jk_<id>_1.png (many songs share one jacket across every difficulty),
        then to any jk_<id>_*.png present, then to `fallback_music_dir` (same
        precedence as s3v_path), then None."""
        n0 = DIFF_JACKET_NUM.get(diff_key, 1)
        for mdir in (music_dir, fallback_music_dir):
            if not mdir:
                continue
            base = os.path.join(mdir, self.folder)
            for n in (n0, 1):
                p = os.path.join(base, "jk_%04d_%d.png" % (self.id, n))
                if os.path.exists(p):
                    return p
            if os.path.isdir(base):
                for fn in sorted(os.listdir(base)):
                    if fn.startswith("jk_%04d_" % self.id) and fn.endswith(".png") \
                            and "_b" not in fn and "_s" not in fn:
                        return os.path.join(base, fn)
        return None

    def thumb_path(self, music_dir, diff_key, fallback_music_dir=None):
        """Small (~108px) jacket variant for on-screen previews - the game
        ships one alongside every full-size jk_<id>_<n>.png as
        jk_<id>_<n>_s.png, cheaper to load/display than resizing the full
        one by hand. Falls back to jacket_path()'s full-size result (the UI
        just displays it a little larger) rather than nothing."""
        n0 = DIFF_JACKET_NUM.get(diff_key, 1)
        for mdir in (music_dir, fallback_music_dir):
            if not mdir:
                continue
            for n in (n0, 1):
                p = os.path.join(mdir, self.folder, "jk_%04d_%d_s.png" % (self.id, n))
                if os.path.exists(p):
                    return p
        return self.jacket_path(music_dir, diff_key, fallback_music_dir)

    def vox_path(self, music_dir, key):
        d = self.difficulties.get(key)
        if not d:
            return None
        p = os.path.join(music_dir, self.folder, "%s_%s.vox" % (self.folder, d.suffix))
        return p if os.path.exists(p) else None

    def s3v_path(self, music_dir, fallback_music_dir=None):
        """The song's audio track, or None if it isn't anywhere findable.

        Chart-only game updates (a difficulty tweak, say) can ship a .vox
        without reshipping its unchanged .s3v - confirmed against a real
        update folder, ~20% of its songs. `fallback_music_dir` (typically a
        fuller/older install's data/music) is checked second when given.
        """
        return self._audio_path(self.folder + ".s3v", music_dir, fallback_music_dir)

    def pre_s3v_path(self, music_dir, fallback_music_dir=None):
        """The song's pre-cut 10-second selection-screen preview, or None.

        Same two-install search as s3v_path, and resolved independently of it, so an update folder that reshipped one and not the other still yields both. Nothing rests on the two coming from the same install: scripts/audio/preview.py verifies the pairing by correlation rather than assuming it.
        """
        return self._audio_path(self.folder + "_pre.s3v", music_dir, fallback_music_dir)

    def _audio_path(self, name, music_dir, fallback_music_dir=None):
        p = os.path.join(music_dir, self.folder, name)
        if os.path.exists(p):
            return p
        if fallback_music_dir:
            p2 = os.path.join(fallback_music_dir, self.folder, name)
            if os.path.exists(p2):
                return p2
        return None


def _text(node, tag, default=""):
    child = node.find(tag) if node is not None else None
    return child.text if child is not None and child.text is not None else default


def _int(node, tag, default=0):
    try:
        return int(_text(node, tag, str(default)))
    except (TypeError, ValueError):
        return default


def _fmt_date(yyyymmdd):
    s = str(yyyymmdd)
    if len(s) == 8 and s.isdigit() and s != "00000000":
        return "%s-%s-%s" % (s[0:4], s[4:6], s[6:8])
    return ""


def parse(music_db_xml_path):
    """-> list[Song], in db order (not necessarily sorted by id)."""
    raw = open(music_db_xml_path, "rb").read()
    text = raw.decode("cp932", errors="replace")
    root = ET.fromstring(text)

    songs = []
    for m in root.findall("music"):
        try:
            song_id = int(m.get("id"))
        except (TypeError, ValueError):
            continue
        info = m.find("info")
        if info is None:
            continue
        ascii_name = _text(info, "ascii")
        song = Song(
            id=song_id,
            folder="%04d_%s" % (song_id, ascii_name),
            title=_text(info, "title_name"),
            artist=_text(info, "artist_name"),
            ascii=ascii_name,
            version=_int(info, "version", 0),
            distribution_date=_fmt_date(_text(info, "distribution_date", "0")),
            genre=_int(info, "genre", 0),
        )
        diffs = m.find("difficulty")
        if diffs is not None:
            for key in DIFF_ORDER:
                node = diffs.find(key)
                if node is None:
                    continue
                song.difficulties[key] = Difficulty(
                    key=key,
                    suffix=DIFF_SUFFIX[key],
                    difnum=_int(node, "difnum", 1),
                    illustrator=_text(node, "illustrator"),
                    effected_by=_text(node, "effected_by"),
                )
        songs.append(song)
    return songs


def fallback_music_dir(base_game_folder):
    """base_game_folder (a full install, for filling in audio/jackets a
    chart-only update didn't reship - see s3v_path) -> its data/music, or
    None if that folder doesn't look like a game install at all."""
    if not base_game_folder:
        return None
    d = os.path.join(base_game_folder, "data", "music")
    return d if os.path.isdir(d) else None


def load_library(game_folder):
    """A game/update folder -> list[Song], restricted to songs that actually
    have a folder under data/music (music_db.xml can list more than a given
    update folder ships charts for - e.g. songs unlocked by later, unrelated
    patches referencing the same shared db snapshot is NOT the case here since
    each update folder carries its own music_db.xml, but being defensive costs
    nothing and matches "two elements that can't be missing" from the caller's
    contract precisely: entries without a matching folder are simply not
    convertible, not an error).
    """
    db_path = os.path.join(game_folder, "data", "others", "music_db.xml")
    music_dir = os.path.join(game_folder, "data", "music")
    if not os.path.isfile(db_path):
        raise FileNotFoundError(db_path)
    if not os.path.isdir(music_dir):
        raise FileNotFoundError(music_dir)
    songs = parse(db_path)
    have = set(os.listdir(music_dir))
    return [s for s in songs if s.folder in have], music_dir
