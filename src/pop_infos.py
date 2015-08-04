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

from gi.repository import Gtk, GLib, Gio, GdkPixbuf

try:
    from lollypop.wikipedia import Wikipedia
except Exception as e:
    print(e)
    print(_("Advanced artist informations disabled"))
    print("$ sudo pip3 install wikipedia")
    Wikipedia = None

try:
    from gi.repository import WebKit
except Exception as e:
    print(e)
    print(_("Wikia support disabled"))
    WebKit = None

from _thread import start_new_thread
from gettext import gettext as _
from cgi import escape

from lollypop.define import Lp


class InfosPopover(Gtk.Popover):
    """
        Popover with artist informations
    """

    def __init__(self, artist, track_id=None):
        """
            Init popover
            @param artist as string
            @param track id as int
        """
        Gtk.Popover.__init__(self)
        self._infos = ArtistInfos(artist, track_id)
        self._infos.show()
        self.add(self._infos)

    def populate(self):
        """
            Populate view
        """
        self._infos.populate()

    def do_show(self):
        """
            Resize popover and set signals callback
        """
        size_setting = Lp.settings.get_value('window-size')
        if isinstance(size_setting[1], int):
            self.set_size_request(700, size_setting[1]*0.7)
        else:
            self.set_size_request(700, 400)
        Gtk.Popover.do_show(self)

    def do_get_preferred_width(self):
        """
            Preferred width
        """
        return (700, 700)


class ArtistInfos(Gtk.Bin):
    """
        Artist informations from lastfm
    """

    def __init__(self, artist, track_id):
        """
            Init artist infos
            @param artist as string
            @param track_id as int
        """
        Gtk.Bin.__init__(self)
        self._liked = True  # Liked track or not?
        self._wikipedia = True
        self._artist = artist
        self._track_id = track_id
        if self._track_id is not None:
            self._title = Lp.tracks.get_name(track_id)
        self._stack = Gtk.Stack()
        self._stack.set_property('expand', True)
        self._stack.show()

        builder = Gtk.Builder()
        builder.add_from_resource('/org/gnome/Lollypop/ArtistInfos.ui')
        builder.connect_signals(self)
        widget = builder.get_object('widget')
        widget.attach(self._stack, 0, 2, 5, 1)

        self._view_btn = builder.get_object('view_btn')
        self._love_btn = builder.get_object('love_btn')
        self._url_btn = builder.get_object('url_btn')
        self._image = builder.get_object('image')
        self._content = builder.get_object('content')

        self._label = builder.get_object('label')
        if self._track_id is None:
            string = "<b>%s</b>" % escape(self._artist)
        else:
            string = "<b>%s</b>   %s" % (escape(self._artist),
                                         escape(self._title))
        self._label.set_markup(string)

        self._spinner = builder.get_object('spinner')
        self._not_found = builder.get_object('notfound')
        self._stack.add(self._spinner)
        self._stack.add(self._not_found)
        
        if Wikipedia is not None or Lp.lastfm is not None:
            self._scrolled_infos = builder.get_object('scrolled')
            self._stack.add(self._scrolled_infos)
            
        if WebKit is not None:
            self._lyrics_btn = builder.get_object('lyrics_btn')
            self._lyrics_btn.show()
            self._scrolled_lyrics = Gtk.ScrolledWindow()
            self._scrolled_lyrics.show()
            self._stack.add(self._scrolled_lyrics)

        self._stack.set_visible_child(self._spinner)
        self.add(widget)

    def populate(self):
        """
            Populate informations and artist image
        """
        start_new_thread(self._populate, ())

#######################
# PRIVATE             #
#######################
    def _populate(self):
        """
            Same as _populate()
            Horrible code limited to two engines, need rework if adding one more
            @thread safe
        """
        url = None
        if self._wikipedia and Wikipedia is not None:
            self._wikipedia = False
            (url, image_url, content) = Wikipedia().get_artist_infos(
                self._artist)
        if url is None and Lp.lastfm is not None:
            self._wikipedia = True
            (url, image_url, content) = Lp.lastfm.get_artist_infos(
                                            self._artist)

        stream = None
        try:
            if image_url is not None:
                f = Gio.File.new_for_uri(image_url)
                (status, data, tag) = f.load_contents()
                if status:
                    stream = Gio.MemoryInputStream.new_from_data(data,
                                                                 None)
        except Exception as e:
            print("PopArtistInfos::_populate: %s" % e)
            content = None

        GLib.idle_add(self._set_content, content, url, stream)

    def _set_content(self, content, url, stream):
        """
            Set content on view
            @param content as str
            @param url as str
            @param stream as Gio.MemoryInputStream
        """
        if self._stack.get_visible_child() == self._scrolled_lyrics:
            self._wikipedia = True
            return

        if content is not None:
            if Lp.lastfm is not None and Wikipedia is not None:
                self._view_btn.show()
            self._stack.set_visible_child(self._scrolled_infos)
            self._url_btn.set_uri(url)
            self._content.set_text(content)
            if self._track_id is not None:
                start_new_thread(self._show_love_btn, ())
            if self._wikipedia:
                self._view_btn.set_tooltip_text(_("Wikipedia"))
                self._url_btn.set_label(_("Last.fm"))
            else:
                self._view_btn.set_tooltip_text(_("Last.fm"))
                self._url_btn.set_label(_("Wikipedia"))
        else:
            self._stack.set_visible_child(self._not_found)
            self._label.set_text(_("No information for this artist..."))
        if stream is not None:
            pixbuf = GdkPixbuf.Pixbuf.new_from_stream_at_scale(stream,
                                                               200,
                                                               -1,
                                                               True,
                                                               None)
            self._image.set_from_pixbuf(pixbuf)
            del pixbuf

    def _show_love_btn(self):
        """
            Show love button
        """
        sql = Lp.db.get_cursor()
        if self._track_id is not None:
            if Lp.playlists.is_present(Lp.playlists._LOVED,
                                       self._track_id,
                                       None,
                                       False,
                                       sql):
                self._liked = False
                self._love_btn.set_tooltip_text(_("I do not love"))
                self._love_btn.set_image(
                    Gtk.Image.new_from_icon_name('face-sick-symbolic',
                                                 Gtk.IconSize.BUTTON))
        GLib.idle_add(self._love_btn.show)
        sql.close()

    def _love_track(self):
        """
            Love a track
            @thread safe
        """
        Lp.playlists.add_loved()

        # Add track to Liked tracks
        sql = Lp.db.get_cursor()
        if self._track_id is not None:
            Lp.playlists.add_track(Lp.playlists._LOVED,
                                   Lp.tracks.get_path(self._track_id,
                                                      sql))
        sql.close()

        Lp.lastfm.love(self._artist, self._title)

    def _unlove_track(self):
        """
            Unlove a track
        """
        Lp.playlists.add_loved()

        # Del track from Liked tracks
        sql = Lp.db.get_cursor()
        if self._track_id is not None:
            Lp.playlists.remove_tracks(
                Lp.playlists._LOVED,
                [Lp.tracks.get_path(self._track_id, sql)])
        sql.close()

        Lp.lastfm.unlove(self._artist, self._title)

    def _on_love_btn_clicked(self, btn):
        """
            Love a track
            @param btn as Gtk.Button
        """
        if self._liked:
            start_new_thread(self._love_track, ())
            btn.set_image(
                Gtk.Image.new_from_icon_name('face-sick-symbolic',
                                             Gtk.IconSize.BUTTON))
            self._liked = False
            btn.set_tooltip_text(_("I do not love"))
        else:
            start_new_thread(self._unlove_track, ())
            btn.set_image(
                Gtk.Image.new_from_icon_name('emblem-favorite-symbolic',
                                             Gtk.IconSize.BUTTON))
            self._liked = True

    def _on_view_clicked(self, btn):
        """
            Next view
            @param btn as Gtk.Button
        """
        self._label.set_text(_("Please wait..."))
        self._view_btn.hide()
        self._love_btn.hide()
        if WebKit is not None:
            self._lyrics_btn.show()
        self._url_btn.set_label('')
        self._stack.set_visible_child(self._spinner)
        self.populate()

    def _on_lyrics_clicked(self, btn):
        """
            Show lyrics from wikia with webkit
        """
        view = self._scrolled_lyrics.get_child()
        if view is None:
            settings = WebKit.WebSettings()
            settings.set_property('enable-private-browsing', True)
            settings.set_property('enable-plugins', False)
            settings.set_property('user-agent',
                                  "Mozilla/5.0 (Linux; <Android Version>;"
                                  " <Build Tag etc.>) AppleWebKit/<WebKit Rev>"
                                  " (KHTML, like Gecko) Chrome/<Chrome Rev>"
                                  " Mobile Safari/<WebKit Rev>")
            view = WebKit.WebView()
            view.set_settings(settings)
            view.show()
            self._scrolled_lyrics.add(view)
        artist = Lp.player.current_track.aartist.replace(' ', '_')
        title = Lp.player.current_track.title.replace(' ', '_')
        url = "http://lyrics.wikia.com/%s:%s" % (artist, title)
        view.load_uri(url)
        self._view_btn.set_tooltip_text(_("Wikipedia"))
        self._view_btn.show()
        self._lyrics_btn.hide()
        self._url_btn.set_label(_("Wikia"))
        self._url_btn.set_uri(url)
        self._stack.set_visible_child(self._scrolled_lyrics)
