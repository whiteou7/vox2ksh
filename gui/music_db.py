"""Reads data/others/music_db.xml (cp932) and matches it to data/music: titles, artists, jackets, levels, and which difficulties have a chart on disk. An input folder can be a partial game update with only the songs it changed, so a chart can exist without its .s3v. Those songs convert without audio unless a fallback game folder is set in Settings.
"""
import os
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

DIFF_ORDER = ["novice", "advanced", "exhaust", "infinite", "maximum"]
DIFF_SUFFIX = {"novice": "1n", "advanced": "2a", "exhaust": "3e",
               "infinite": "4i", "maximum": "5m"}
DIFF_SHORT = {"novice": "NOV", "advanced": "ADV", "exhaust": "EXH",
              "infinite": "INF", "maximum": "MXM"}
DIFF_TILE = {"novice": 1, "advanced": 2, "exhaust": 3, "infinite": 4, "maximum": 4}

DIFF_JACKET_NUM = {"novice": 1, "advanced": 2, "exhaust": 3, "infinite": 4, "maximum": 5}

VERSION_NAME = {
    1: "BOOTH", 2: "INFINITE INFECTION", 3: "GRAVITY WARS",
    4: "HEAVENLY HAVEN", 5: "VIVID WAVE", 6: "EXCEED GEAR",
    7: "NABLA"
}


@dataclass
class Difficulty:
    key: str
    suffix: str
    difnum: int
    illustrator: str
    effected_by: str

    @property
    def level_display(self):
        if self.difnum % 10 == 0:
            return str(self.difnum // 10)
        return "%.1f" % (self.difnum / 10.0)

    @property
    def level_int(self):
        return max(1, min(20, self.difnum // 10))


@dataclass
class Song:
    id: int
    folder: str
    title: str
    artist: str
    ascii: str
    version: int
    distribution_date: str
    genre: int
    difficulties: dict = field(default_factory=dict)

    @property
    def version_name(self):
        return VERSION_NAME.get(self.version, str(self.version))

    def top_difficulty(self):
        return self.difficulties.get("maximum") or self.difficulties.get("infinite")

    def resolve_diff_keys(self, diff_keys):
        """`diff_keys` with the pseudo-key "top" replaced by this song's top difficulty, if it has one."""
        keys = set(diff_keys)
        if "top" in keys:
            keys.discard("top")
            top = self.top_difficulty()
            if top:
                keys.add(top.key)
        return keys

    def difficulty_tiles(self):
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
        preferred_number = DIFF_JACKET_NUM.get(diff_key, 1)
        for music_root in (music_dir, fallback_music_dir):
            if not music_root:
                continue
            base = os.path.join(music_root, self.folder)
            for n in (preferred_number, 1):
                p = os.path.join(base, "jk_%04d_%d_b.png" % (self.id, n))
                if os.path.exists(p):
                    return p
            if os.path.isdir(base):
                for fn in sorted(os.listdir(base)):
                    if fn.startswith("jk_%04d_" % self.id) and fn.endswith("_b.png"):
                        return os.path.join(base, fn)
        return None

    def thumb_path(self, music_dir, diff_key, fallback_music_dir=None):
        preferred_number = DIFF_JACKET_NUM.get(diff_key, 1)
        for music_root in (music_dir, fallback_music_dir):
            if not music_root:
                continue
            for n in (preferred_number, 1):
                p = os.path.join(music_root, self.folder, "jk_%04d_%d_s.png" % (self.id, n))
                if os.path.exists(p):
                    return p
        return self.jacket_path(music_dir, diff_key, fallback_music_dir)

    def vox_path(self, music_dir, key):
        difficulty = self.difficulties.get(key)
        if not difficulty:
            return None
        path = os.path.join(music_dir, self.folder, "%s_%s.vox" % (self.folder, difficulty.suffix))
        return path if os.path.exists(path) else None

    def s3v_path(self, music_dir, fallback_music_dir=None):
        return self._find_audio_file(self.folder + ".s3v", music_dir, fallback_music_dir)

    def pre_s3v_path(self, music_dir, fallback_music_dir=None):
        return self._find_audio_file(self.folder + "_pre.s3v", music_dir, fallback_music_dir)

    def _find_audio_file(self, name, music_dir, fallback_music_dir=None):
        path = os.path.join(music_dir, self.folder, name)
        if os.path.exists(path):
            return path
        if fallback_music_dir:
            fallback_path = os.path.join(fallback_music_dir, self.folder, name)
            if os.path.exists(fallback_path):
                return fallback_path
        return None


def _child_text(node, tag, default=""):
    child = node.find(tag) if node is not None else None
    return child.text if child is not None and child.text is not None else default


def _child_int(node, tag, default=0):
    try:
        return int(_child_text(node, tag, str(default)))
    except (TypeError, ValueError):
        return default


def _format_date(yyyymmdd):
    s = str(yyyymmdd)
    if len(s) == 8 and s.isdigit() and s != "00000000":
        return "%s-%s-%s" % (s[0:4], s[4:6], s[6:8])
    return ""


def parse_music_db(music_db_xml_path):
    raw = open(music_db_xml_path, "rb").read()
    text = raw.decode("cp932", errors="replace")
    root = ET.fromstring(text)

    songs = []
    for music_node in root.findall("music"):
        try:
            song_id = int(music_node.get("id"))
        except (TypeError, ValueError):
            continue
        info = music_node.find("info")
        if info is None:
            continue
        ascii_name = _child_text(info, "ascii")
        song = Song(
            id=song_id,
            folder="%04d_%s" % (song_id, ascii_name),
            title=_child_text(info, "title_name"),
            artist=_child_text(info, "artist_name"),
            ascii=ascii_name,
            version=_child_int(info, "version", 0),
            distribution_date=_format_date(_child_text(info, "distribution_date", "0")),
            genre=_child_int(info, "genre", 0),
        )
        diffs = music_node.find("difficulty")
        if diffs is not None:
            for key in DIFF_ORDER:
                node = diffs.find(key)
                if node is None:
                    continue
                song.difficulties[key] = Difficulty(
                    key=key,
                    suffix=DIFF_SUFFIX[key],
                    difnum=_child_int(node, "difnum", 1),
                    illustrator=_child_text(node, "illustrator"),
                    effected_by=_child_text(node, "effected_by"),
                )
        songs.append(song)
    return songs


def install_music_dir(base_game_folder):
    if not base_game_folder:
        return None
    d = os.path.join(base_game_folder, "data", "music")
    return d if os.path.isdir(d) else None


def load_library(game_folder):
    db_path = os.path.join(game_folder, "data", "others", "music_db.xml")
    music_dir = os.path.join(game_folder, "data", "music")
    if not os.path.isfile(db_path):
        raise FileNotFoundError(db_path)
    if not os.path.isdir(music_dir):
        raise FileNotFoundError(music_dir)
    songs = parse_music_db(db_path)
    have = set(os.listdir(music_dir))
    return [s for s in songs if s.folder in have], music_dir
