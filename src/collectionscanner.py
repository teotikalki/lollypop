#!/usr/bin/python
# Copyright (c) 2014-2015 Cedric Bellegarde <cedric.bellegarde@adishatz.org>
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <http://www.gnu.org/licenses/>.

import os
from time import sleep, time
from gettext import gettext as _
from gi.repository import GLib, GObject, Gio
from _thread import start_new_thread

from lollypop.define import Objects, Navigation
from lollypop.tagreader import ScannerTagReader
from lollypop.utils import is_audio, debug


class CollectionScanner(GObject.GObject, ScannerTagReader):
    __gsignals__ = {
        'scan-finished': (GObject.SignalFlags.RUN_FIRST, None, ()),
        'artist-update': (GObject.SignalFlags.RUN_FIRST, None, (int, int)),
        'genre-update': (GObject.SignalFlags.RUN_FIRST, None, (int,)),
        'added': (GObject.SignalFlags.RUN_FIRST, None, (int, bool))
    }

    """
        Init scanner
    """
    def __init__(self):
        GObject.GObject.__init__(self)
        ScannerTagReader.__init__(self)
        self._is_empty = True
        self._in_thread = False
        self._is_locked = False

    """
        Set progress bar to be filed
        @warning Mandatory
        @param progress as Gtk.Progress
    """
    def set_progress(self, progress):
        self._progress = progress

    """
        Update database
        @param smooth as bool, if smooth, try to scan smoothly
    """
    def update(self, smooth):
        paths = Objects.settings.get_value('music-path')
        if not paths:
            if GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_MUSIC):
                paths = [GLib.get_user_special_dir(
                                          GLib.UserDirectory.DIRECTORY_MUSIC)]
            else:
                print("You need to add a music path"
                      " to org.gnome.Lollypop in dconf")
                return

        if not self._in_thread:
            if Objects.notify is not None:
                Objects.notify.send(_("Your music is updating"))
            self._progress.show()
            self._in_thread = True
            self._is_locked = True
            self._compilations = []
            self._mtimes = Objects.tracks.get_mtimes()
            start_new_thread(self._scan, (paths, smooth))

    """
        Add specified files to collection
        @param files as [Gio.Files]
        @thread safe
    """
    def add(self, files):
        if not files:
            return
        self._in_thread = True
        self._is_locked = True
        start_new_thread(self._add, (files,))

    """
        Return True if db locked
    """
    def is_locked(self):
        return self._is_locked

    """
        Stop scan
    """
    def stop(self):
        self._progress.hide()
        self._in_thread = False

#######################
# PRIVATE             #
#######################
    """
        Return all tracks for paths
        @param paths as string
        @return ([tracks path], count)
    """
    def _get_tracks_for_paths(self, paths):
        tracks = []
        count = 0
        for path in paths:
            for root, dirs, files in os.walk(path):
                for name in files:
                    filepath = os.path.join(root, name)
                    f = Gio.File.new_for_path(filepath)
                    if is_audio(f):
                        tracks.append(filepath)
                        count += 1
                    else:
                        debug("%s not detected as a music file" % filepath)
        return (tracks, count)

    """
        Update progress bar status
        @param scanned items as int, total items as int
    """
    def _update_progress(self, current, total):
        self._progress.set_fraction(current/total)

    """
        Notify from main thread when scan finished
    """
    def _finish(self):
        self._progress.hide()
        self._progress.set_fraction(0.0)
        self._in_thread = False
        self._is_locked = False
        self.emit("scan-finished")

    """
        Clean track's compilation if needed
        @param album id as int
    """
    def _clean_compilation(self, album_id, sql=None):
        artists = Objects.albums.get_compilation_artists(album_id, sql)
        # It's not a compilation anymore
        if len(artists) == 1:
            artist_id = artists[0]
            Objects.albums.set_artist_id(album_id, artist_id, sql)
            # Update album path
            tracks = Objects.albums.get_tracks(album_id, None, sql)
            filepath = Objects.tracks.get_path(tracks[0], sql)
            path = os.path.dirname(filepath)
            Objects.albums.set_path(album_id, path, sql)

    """
        Add specified files to collection
        @param files as [Gio.Files]
        @thread safe
    """
    def _add(self, files):
        GLib.idle_add(self._progress.show)
        sql = Objects.db.get_cursor()
        tracks = Objects.tracks.get_paths(sql)
        count = len(files)
        i = 0
        GLib.idle_add(self._update_progress, i, count)
        for f in files:
            track_id = None
            if not self._in_thread:
                sql.close()
                self._is_locked = False
                return
            if f not in tracks:
                infos = self.get_infos(f)
                if infos is not None:
                    debug("Adding file: %s" % f)
                    track_id = self._add2db(f, 0, infos, True, sql)
                else:
                    print("Can't get infos for ", f)
            else:
                track_id = Objects.tracks.get_id_by_path(f, sql)
            if track_id is not None:
                if i == 0:
                    sql.commit()
                GLib.idle_add(self.emit, "added", track_id, i==0)
            i += 1
            GLib.idle_add(self._update_progress, i, count)
        Objects.albums.search_compilations(True, sql)
        sql.commit()
        sql.close()
        GLib.idle_add(self._progress.hide)
        self._in_thread = False
        self._is_locked = False

    """
        Scan music collection for music files
        @param paths as [string], paths to scan
        @param smooth as bool
        @thread safe
    """
    def _scan(self, paths, smooth):
        sql = Objects.db.get_cursor()
        orig_tracks = Objects.tracks.get_paths(sql)
        self._is_empty = len(orig_tracks) == 0
        # Clear cover cache
        if not smooth:
            Objects.art.clean_all_cache(sql)

        (new_tracks, count) = self._get_tracks_for_paths(paths)

        i = 0
        for filepath in new_tracks:
            if not self._in_thread:
                sql.close()
                self._is_locked = False
                return
            GLib.idle_add(self._update_progress, i, count)
            mtime = int(os.path.getmtime(filepath))
            try:
                if filepath not in orig_tracks:
                    infos = self.get_infos(filepath)
                    if infos is not None:
                        debug("Adding file: %s" % filepath)
                        self._add2db(filepath, mtime, infos, False, sql)
                    else:
                        print("Can't get infos for ", filepath)
                else:
                    # Update tags by removing song and readd it
                    if mtime != self._mtimes[filepath]:
                        track_id = Objects.tracks.get_id_by_path(filepath, sql)
                        album_id = Objects.tracks.get_album_id(track_id, sql)
                        Objects.tracks.remove(filepath, sql)
                        self._clean_compilation(album_id, sql)
                        infos = self.get_infos(filepath)
                        if infos is not None:
                            debug("Adding file: %s" % filepath)
                            self._add2db(filepath, mtime, infos, False, sql)
                        else:
                            print("Can't get infos for ", filepath)
                    orig_tracks.remove(filepath)

            except Exception as e:
                print(ascii(filepath))
                print("CollectionScanner::_scan(): %s" % e)
            i += 1
            if smooth:
                sleep(0.001)

        # Clean deleted files
        if i > 0:
            for filepath in orig_tracks:
                track_id = Objects.tracks.get_id_by_path(filepath, sql)
                album_id = Objects.tracks.get_album_id(track_id, sql)
                Objects.tracks.remove(filepath, sql)
                self._clean_compilation(album_id, sql)

        Objects.tracks.clean(sql)
        Objects.albums.search_compilations(False, sql)
        self._restore_popularities(sql)
        self._restore_mtimes(sql)
        sql.commit()
        sql.close()
        GLib.idle_add(self._finish)

    """
        Add new file to db with informations
        @param filepath as string
        @param file modification time as int
        @param infos as GstPbutils.DiscovererInfo
        @param outside as bool
        @param sql as sqlite cursor
        @return track id as int
    """
    def _add2db(self, filepath, mtime, infos, outside, sql):
        tags = infos.get_tags()

        title = self.get_title(tags, filepath)
        artists = self.get_artists(tags)
        album_artist = self.get_album_artist(tags)
        album_name = self.get_album_name(tags)
        genres = self.get_genres(tags)
        discnumber = self.get_discnumber(tags)
        tracknumber = self.get_tracknumber(tags)
        year = self.get_year(tags)
        length = infos.get_duration()/1000000000

        (artist_ids, new_artist_ids) = self.add_artists(artists,
                                                         album_artist,
                                                         outside,
                                                         sql)

        (album_artist_id, new) = self.add_album_artist(album_artist, outside, sql)
        if new:
            new_artist_ids.append(album_artist_id)

        album_id = self.add_album(album_name, album_artist_id,
                                   filepath, outside, sql)

        (genre_ids, new_genre_ids) = self.add_genres(genres, album_id,
                                                      outside, sql)

        # Add track to db
        Objects.tracks.add(title, filepath, length,
                           tracknumber, discnumber,
                           album_id, year, mtime, outside, sql)

        self.update_year(album_id, sql)

        track_id = Objects.tracks.get_id_by_path(filepath, sql)
        self.update_track(track_id, artist_ids, genre_ids, outside, sql)

        # Notify about new artists/genres
        if new_genre_ids or new_artist_ids:
            sql.commit()
            for genre_id in new_genre_ids:
                GLib.idle_add(self.emit, "genre-update", genre_id)
            for artist_id in new_artist_ids:
                GLib.idle_add(self.emit, "artist-update", artist_id, album_id)
        return track_id

    """
        Restore albums popularties
    """
    def _restore_popularities(self, sql):
        self._popularities = Objects.db.get_popularities()
        result = sql.execute("SELECT albums.name, artists.name, albums.rowid\
                              FROM albums, artists\
                              WHERE artists.rowid == albums.artist_id")
        for row in result:
            string = "%s_%s" % (row[0], row[1])
            if string in self._popularities:
                Objects.albums.set_popularity(row[2],
                                              self._popularities[string], sql)
    """
        Restore albums mtimes
    """
    def _restore_mtimes(self, sql):
        self._mtimes = Objects.db.get_mtimes()
        result = sql.execute("SELECT albums.name, artists.name, albums.rowid\
                              FROM albums, artists\
                              WHERE artists.rowid == albums.artist_id")
        for row in result:
            string = "%s_%s" % (row[0], row[1])
            if string in self._mtimes:
                Objects.albums.set_mtime(row[2],
                                         self._mtimes[string], sql)
