# from libs.db_mongo import MongoDatabase
import csv
# !/usr/bin/python
import threading
from itertools import zip_longest as izip_longest

import numpy as np
import pygame
from kivy.animation import Animation
from kivy.clock import Clock, mainthread
from kivy.core.audio import SoundLoader
from kivy.core.text import LabelBase
from kivy.core.window import Window
from kivy.lang import Builder
from kivy.loader import Loader
from kivy.properties import NumericProperty, ObjectProperty, StringProperty
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.image import AsyncImage, Image
from kivy.uix.screenmanager import Screen, ScreenManager
from kivy.uix.widget import Widget
from kivymd.app import MDApp
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.screen import MDScreen
from kivymd.uix.tab import MDTabsBase
from lyricsgenius import Genius
from lyricsgenius.api.public_methods import SearchMethods
from lyricsgenius.types import Song
from termcolor import colored

import libs.fingerprint as fingerprint
from libs.config import get_config
from libs.db_sqlite import SqliteDatabase, SQLITE_MAX_VARIABLE_NUMBER
from libs.reader_microphone import MicrophoneReader
from libs.visualiser_console import VisualiserConsole as visual_peak
from libs.visualiser_plot import VisualiserPlot as visual_plot

token = "uK8aNujohVZzI6BtyovEc7rPndKeRez3MmnqrcH12_qFk0ZFWhcAyCt7VCmk7VKs"
f = open('D:\\kivy mobile app\\top50\\top100.csv')
reader = csv.reader(f)
dict_songs = {}
for row in reader:
    dict_songs[row[0]] = {'artist': row[1], 'year': row[3], 'beats_per_minute': row[4], 'energy': row[5],
                          'danceability': row[6], 'popularity': row[13]}

Window.size = (320, 600)
Builder.load_file('app2.kv')
LabelBase.register(name="VastShadow", fn_regular="VastShadow-Regular.ttf")
LabelBase.register(name="Flavors", fn_regular="Flavors-Regular.ttf")
LabelBase.register(name="BadScript", fn_regular="BadScript-Regular.ttf")


class MyGenius(Genius):
    def search_song(self, title=None, artist="", song_id=None, get_full_info=True):
        msg = "You must pass either a `title` or a `song_id`."
        if title is None and song_id is None:
            assert any([title, song_id]), msg

        if self.verbose and title:
            if artist:
                print('Searching for "{s}" by {a}...'.format(s=title, a=artist))
            else:
                print('Searching for "{s}"...'.format(s=title))

        if song_id:
            result = self.song(song_id)['song']
        else:
            search_term = "{s} {a}".format(s=title, a=artist).strip()
            # search_response = self.search_all(search_term)

            search_response = SearchMethods.search(self, search_term=search_term, type_="song")
            result = self._get_item_from_search_response(search_response,
                                                         title,
                                                         type_="song",
                                                         result_type="title")

        # Exit search if there were no results returned from API
        # Otherwise, move forward with processing the search results
        if result is None:
            if self.verbose and title:
                print("No results found for: '{s}'".format(s=search_term))
            return None

        # Reject non-songs (Liner notes, track lists, etc.)
        # or songs with uncomplete lyrics (e.g. unreleased songs, instrumentals)
        if self.skip_non_songs and not self._result_is_lyrics(result):
            valid = False
        else:
            valid = True

        if not valid:
            if self.verbose:
                print('Specified song does not contain lyrics. Rejecting.')
            return None

        song_id = result['id']

        # Download full song info (an API call) unless told not to by user
        song_info = result
        if song_id is None and get_full_info is True:
            new_info = self.song(song_id)['song']
            song_info.update(new_info)

        if (song_info['lyrics_state'] == 'complete'
            and not song_info.get('instrumental')):
            lyrics = self.lyrics(song_url=song_info['url'])
        else:
            lyrics = ""

        # Skip results when URL is a 404 or lyrics are missing
        if self.skip_non_songs and not lyrics:
            if self.verbose:
                print('Specified song does not have a valid lyrics. '
                      'Rejecting.')
            return None

        # Return a Song object with lyrics if we've made it this far
        song = Song(self, song_info, lyrics)
        if self.verbose:
            print('Done.')
        return song


genius = MyGenius(token)
genius.remove_section_headers = True  # Remove section headers (e.g. [Chorus]) from lyrics when searching
# genius.excluded_terms = ["(Remix)", "(Live)",
#                          "Today’s Top Hits 9/11/20"]  # Exclude songs with these words in their title


class LoaderImage(AsyncImage):
    Loader.loading_image = 'D:\\kivy mobile app\\images\\loader.gif'


class Music():
    @staticmethod
    def align_matches(matches):
        db = SqliteDatabase()
        diff_counter = {}
        largest = 0
        largest_count = 0
        song_id = -1

        for tup in matches:
            sid, diff = tup

            if diff not in diff_counter:
                diff_counter[diff] = {}

            if sid not in diff_counter[diff]:
                diff_counter[diff][sid] = 0

            diff_counter[diff][sid] += 1

            if diff_counter[diff][sid] > largest_count:
                largest = diff
                largest_count = diff_counter[diff][sid]
                song_id = sid

        songM = db.get_song_by_id(song_id)

        nseconds = round(float(largest) / fingerprint.DEFAULT_FS *
                         fingerprint.DEFAULT_WINDOW_SIZE *
                         fingerprint.DEFAULT_OVERLAP_RATIO, 5)

        return {
            "SONG_ID": song_id,
            "SONG_NAME": songM[1],
            "CONFIDENCE": largest_count,
            "OFFSET": int(largest),
            "OFFSET_SECS": nseconds
        }

    @staticmethod
    def grouper(iterable, n, fillvalue=None):
        args = [iter(iterable)] * n
        return (filter(None, values)
                for values in izip_longest(fillvalue=fillvalue, *args))

    @staticmethod
    def find_matches(samples, Fs=fingerprint.DEFAULT_FS):
        hashes = fingerprint.fingerprint(samples, Fs=Fs)
        return Music.return_matches(hashes)

    @staticmethod
    def return_matches(hashes):
        mapper = {}
        db = SqliteDatabase()
        for hash, offset in hashes:
            mapper[hash.upper()] = offset
        values = mapper.keys()

        for split_values in map(list, Music.grouper(values, SQLITE_MAX_VARIABLE_NUMBER)):
            # @todo move to db related files
            query = """
        SELECT upper(hash), song_fk, offset
        FROM fingerprints
        WHERE upper(hash) IN (%s)
      """
            query = query % ', '.join('?' * len(split_values))

            x = db.executeAll(query, split_values)
            matches_found = len(x)

            if matches_found > 0:
                msg = '   ** found %d hash matches (step %d/%d)'
                print(colored(msg, 'green') % (
                    matches_found,
                    len(split_values),
                    len(values)
                ))
            else:
                msg = '   ** not matches found (step %d/%d)'
                print(colored(msg, 'red') % (len(split_values), len(values)))

            for hash_code, sid, offset in x:
                # (sid, db_offset - song_sampled_offset)
                if isinstance(offset, bytes):
                    # offset come from fingerprint.py and numpy extraction/processing
                    offset = np.frombuffer(offset, dtype=np.int)[0]
                yield sid, offset - mapper[hash_code]


class Sounds(MDScreen):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.thread = None

    def apasa(self):
        self.ids.img.source = 'listen.gif'
       # self.ids.my_md.on_action_button = main()

    def release(self):
        self.ids.my_label.text = "Tap the mic for listening ..."
        if self.ids.my_md.icon == 'microphone-off':
            self.ids.my_md.icon = 'microphone'
        else:
            self.ids.my_md.icon = 'microphone-off'

    def msg(self):
        if self.ids.my_md.icon == 'microphone-off':
            self.ids.my_md.icon = 'microphone'
            self.ids.my_label.text = "Listening ..."
            return self.main
        else:
            self.ids.my_md.icon = 'microphone-off'
            self.ids.my_label.text = "Tap the mic for listening ..."

    def test(self):
        self.thread = threading.Thread(target=self.main).start()

    @mainthread
    def test2(self):
        self.ids.img.source = 'D:\\kivy mobile app\\images\\processing-sounds.gif'
        self.ids.img.anim_delay = 0.05
        self.ids.my_label.text = ""

    def main(self):
        self.test2()
        if self.ids.my_md.icon == 'microphone-off':
            #self.ids.img.source = 'listen.gif'
            self.ids.my_md.icon = 'microphone'
            #db = SqliteDatabase()

            msg = ' * started recording..'
            print(msg)
            config = get_config()
            # parser = argparse.ArgumentParser(formatter_class=RawTextHelpFormatter)
            # parser.add_argument('-s', '--seconds', nargs='?')
            # args = parser.parse_args()

            # if not args.seconds:
            #    parser.print_help()
            #    sys.exit(0)

            seconds = 5

            chunksize = 2 ** 12  # 4096
            channels = 2  # int(config['channels']) # 1=mono, 2=stereo

            record_forever = False
            visualise_console = bool(config['mic.visualise_console'])
            visualise_plot = bool(config['mic.visualise_plot'])

            reader = MicrophoneReader(None)

            reader.start_recording(seconds=seconds,
                                   chunksize=chunksize,
                                   channels=channels)

            msg = ' * started recording..'
            print(colored(msg, attrs=['dark']))

            while True:
                bufferSize = int(reader.rate / reader.chunksize * seconds)

                for i in range(0, bufferSize):
                    nums = reader.process_recording()

                    if visualise_console:
                        msg = colored('   %05d', attrs=['dark']) + colored(' %s', 'green')
                        print(msg % visual_peak.calc(nums))
                    else:
                        msg = '   processing %d of %d..' % (i, bufferSize)
                        print(colored(msg, attrs=['dark']))

                if not record_forever:
                    break

            if visualise_plot:
                data = reader.get_recorded_data()[0]
                visual_plot.show(data)

            reader.stop_recording()

            msg = ' * recording has been stopped'
            print(colored(msg, attrs=['dark']))

            data = reader.get_recorded_data()

            msg = ' * recorded %d samples'
            print(colored(msg, attrs=['dark']) % len(data[0]))

            # reader.save_recorded('test.wav')

            Fs = fingerprint.DEFAULT_FS
            channel_amount = len(data)

            result = set()
            matches = []
            m = Music()
            for channeln, channel in enumerate(data):
                # TODO: Remove prints or change them into optional logging.
                msg = '   fingerprinting channel %d/%d'
                print(colored(msg, attrs=['dark']) % (channeln + 1, channel_amount))

                matches.extend(m.find_matches(channel))

                msg = '   finished channel %d/%d, got %d hashes'
                print(colored(msg, attrs=['dark']) % (channeln + 1,
                                                      channel_amount, len(matches)))

            total_matches_found = len(matches)

            print('')
            # print(total_matches_found)
            music = Music()

            if total_matches_found > 0:
                msg = ' ** totally found %d hash matches'
                print(colored(msg, 'green') % total_matches_found)

                song = music.align_matches(matches)

                if song['CONFIDENCE'] >= 20:

                    msg = ' => song: %s (id=%d)\n'
                    msg += '    offset: %d (%d secs)\n'
                    msg += '    confidence: %d'

                    print(colored(msg, 'green') % (song['SONG_NAME'], song['SONG_ID'],
                                                   song['OFFSET'], song['OFFSET_SECS'],
                                                   song['CONFIDENCE']))

                    x = song['SONG_NAME'].split('- ')
                    y = x[1].split('.wav')
                    sn = y[0]
                    print(sn)
                    # self.ids.my_label.text = song['SONG_NAME']
                    # print(sn)
                    # print(dict_songs[sn]['artist'])
                    # print(self.ids.my_label.text)

                    # print(ScreenManager().screen_names)
                    # ScreenManager().get_screen('second-screen').ids.song_name.text = song['SONG_NAME']
                    # self.ids.my_label.font_name = 'Flavors'
                    # self.ids.my_label.text_color = '#ffdc00'

                    song = genius.search_song(sn, dict_songs[sn]['artist'], get_full_info=False)
                    if not song:
                        lyrics = "No lyrics found!"
                    else:
                        lyrics = song.lyrics

                    print(song.song_art_image_url)
                    # print(sn)
                    # print(dict_songs[sn])

                    self.manager.get_screen('second-screen').song_name.text = sn
                    self.manager.get_screen('second-screen').artist_name.text = dict_songs[sn]['artist']
                    self.manager.get_screen('second-screen').cov_img.source = song.song_art_image_url
                    self.manager.get_screen('second-screen').rot_img.source = song.header_image_thumbnail_url
                    #self.manager.get_screen('third-screen').det_img.source = song.song_art_image_url
                    self.manager.get_screen('third-screen').year.subtext = dict_songs[sn]['year']
                    self.manager.get_screen('third-screen').bmp.subtext = dict_songs[sn]['beats_per_minute']
                    self.manager.get_screen('third-screen').energy.subtext = dict_songs[sn]['energy'] + "%"
                    self.manager.get_screen('third-screen').danceability.subtext = dict_songs[sn]['danceability'] + "%"
                    self.manager.get_screen('third-screen').popularity.subtext = dict_songs[sn]['popularity'] + "%"
                    self.manager.get_screen('third-screen').song.text = dict_songs[sn]['artist'] + " - " + sn
                    self.manager.get_screen('third-screen').my_lyrics.text = lyrics
                    self.manager.get_screen('third-screen').song_miniplayer.text = '[b]' + dict_songs[sn]['artist'] + '[/b]' + '\n' + sn

                    music = SoundLoader.load(
                        'D:\\kivy mobile app\\wav\\' + dict_songs[sn]['artist'] + ' - ' + sn + '.wav')
                    print(music.length / 60)
                    dur1 = music.length / 60
                    dur2 = (dur1 - int(dur1)) * 100
                    dur1 = int(dur1)
                    dur2 = int(dur2)
                    self.manager.get_screen('third-screen').duration.subtext = str(dur1) + " min. " + str(
                        dur2) + " sec."
                    self.ids.my_md.icon = 'microphone-off'
                    self.ids.my_label.text = dict_songs[sn]['artist'] + '-' + sn
                    self.ids.mp_btn.disabled = False
                    self.ids.details_btn.disabled = False
                    self.ids.img.source = 'D:\\kivy mobile app\\images\\transparent.png'
                    #self.ids.img.anim_delay = 0.7
                    self.manager.current = 'second-screen'

                else:
                    msg = ' ** not matches found at all, confidence is: %d'
                    print(colored(msg, 'red') % song['CONFIDENCE'])
                    self.ids.my_label.text = 'Song not found!\n Please try again.'
                    self.ids.my_md.icon = 'microphone-off'
                    self.ids.mp_btn.disabled = True
                    self.ids.details_btn.disabled = True
                    self.ids.img.source = 'D:\\kivy mobile app\\images\\transparent.png'
                    #self.ids.img.anim_delay = 0.7
            else:
                self.ids.my_label.text = 'Song not found!\n Please try again.'
                self.ids.img.source = 'D:\\kivy mobile app\\images\\transparent.png'
                #self.ids.img.anim_delay = 0.7

            self.ids.my_md.icon = 'microphone-off'
            #self.ids.my_label.text = "Tap the button for listening ..."
            #self.ids.img.source = 'D:\\kivy mobile app\\images\\transparent.png'
            self.ids.img.source = 'D:\\kivy mobile app\\images\\transparent.png'
            #self.ids.img.anim_delay = 0.7
            #if self.thread:



    def printreleased(self):
        print("released")


class MusicScreen(Screen):
    pass

class WelcomeScreen(MDScreen):

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # Delay time for splash screen before transitioning to main screen
        Clock.schedule_once(self.change_screen, 10)  # Delay for 10 seconds
    ########################################################################
    ## This function changes the current screen to main screen
    ########################################################################
    def change_screen(self, dt):
        self.manager.current = "first-screen"

class DetailsScreen(MDBoxLayout):
    music = SoundLoader.load('D:\\kivy mobile app\\wav\\Imagine Dragons - Believer.wav')
    progress = Animation(value=music.length, d=music.length, t='linear')
    #pygame.init()
    #pygame.mixer.init()
    playing_state = False
    is_playing = False
    def play_music_from_details_screen(self, widget):
        self.widget = widget
        self.progress.start(widget)
        txt = self.song_miniplayer.text
        x = txt.split("\n")
        sn = x[1]
        a1 = x[0].split("[b]")
        an = a1[1].split("[/b]")
        if self.play_details.icon == 'play-outline' and self.is_playing == False:
            music = SoundLoader.load(
                'D:\\kivy mobile app\\wav\\' + an[0] + ' - ' + sn + '.wav')
            pygame.mixer.music.load(
                'D:\\kivy mobile app\\wav\\' + an[0] + ' - ' + sn + '.wav')
            self.progress = Animation(value=music.length, d=music.length, t='linear')
            pygame.mixer.music.play()
            self.is_playing = True
            self.play_details.icon = 'pause'
            self.progress_details.max = self.screen_mng.get_screen('second-screen').progr.max
            self.progress_details.min = self.screen_mng.get_screen('second-screen').progr.min
            #self.screen_mng.get_screen('second-screen').progress = self.progress
            self.screen_mng.get_screen('second-screen').play_pause.icon = self.play_details.icon
            #print(self.screen_mng.get_screen('second-screen').play_pause.icon)

            self.progress.start(widget)
            #self.anim.start(self)

            # self.rotate()
        elif self.play_details.icon == 'pause' and not self.playing_state:
            pygame.mixer.music.pause()
            self.play_details.icon = 'play-outline'
            #self.screen_mng.get_screen('second-screen').progress = self.progress
            self.screen_mng.get_screen('second-screen').play_pause.icon = self.play_details.icon
            self.playing_state = True
            self.progress.stop(widget)
            #self.anim.stop(self)
        else:
            pygame.mixer.music.unpause()
            self.play_details.icon = 'pause'
            #self.screen_mng.get_screen('second-screen').progress = self.progress
            self.screen_mng.get_screen('second-screen').play_pause.icon = self.play_details.icon
            self.playing_state = False
            self.progress.start(widget)
            #self.anim.start(self)
            # self.rotate()

class SongDetailsScreen(Screen):
    def on_tab_switch(self, instance_tabs, instance_tab, instance_tab_label, tab_text):
        instance_tab.ids.label.text = tab_text


class RoundedImage(Widget):
    texture = ObjectProperty(None)
    source = StringProperty('')

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        Clock.schedule_once(self.create_texture, 1)

    def create_texture(self, *args):
        image = Image(source=self.source, allow_stretch=True, keep_ratio=False,
            size_hint=(None, None), size=self.size)
        self.texture = image.texture

class SongCover(MDBoxLayout):
    music = SoundLoader.load('D:\\kivy mobile app\\wav\\Imagine Dragons - Believer.wav')
    #print(music.length)
    angle = NumericProperty()
    anim = Animation(angle=-360, d=3, t='linear')
    anim += Animation(angle=0, d=0, t='linear')
    progress = Animation(value=music.length, d=music.length, t='linear')
    anim.repeat = True
    pygame.init()
    pygame.mixer.init()
    playing_state = False
    is_playing = False

    def rotate(self):
        # print(self.song_name.text)
        # print(ScreenManager().get_screen('second-screen').song_name.text)
        if self.anim.have_properties_to_animate(self):
            self.anim.stop(self.widget)
            # self.progress.stop(self.widget)
        else:
            self.anim.start(self)
            # self.progress.start(self.widget)

    def play_music(self, widget):
        self.widget = widget
        self.progress.start(widget)
        if (self.screen_mng.get_screen('third-screen').play_details.icon == 'play-outline'):
            playing_state = False
            is_playing = False
        else:
            is_playing = True
        self.img.source = 'D:\\kivy mobile app\\images\\giphy.gif'
        if self.play_pause.icon == 'play-outline' and self.is_playing == False:
            music = SoundLoader.load(
                'D:\\kivy mobile app\\wav\\' + self.artist_name.text + ' - ' + self.song_name.text + '.wav')
            pygame.mixer.music.load(
                'D:\\kivy mobile app\\wav\\' + self.artist_name.text + ' - ' + self.song_name.text + '.wav')
            self.progress = Animation(value=music.length, d=music.length, t='linear')
            pygame.mixer.music.play()
            self.is_playing = True
            self.play_pause.icon = 'pause'
            self.progr.max = music.length
            self.progr.min = 0
            self.progress.start(widget)
            self.anim.start(self)
            #self.screen_mng.get_screen('third-screen').progress_details = self.progress
            self.screen_mng.get_screen('third-screen').play_details.icon = self.play_pause.icon
            # self.rotate()
        elif self.play_pause.icon == 'pause' and not self.playing_state:
            pygame.mixer.music.pause()
            self.play_pause.icon = 'play-outline'
            #self.screen_mng.get_screen('third-screen').progress_details = self.progress
            #self.screen_mng.get_screen('third-screen').play_details.icon = self.play_pause.icon
            self.playing_state = True
            self.progress.stop(widget)
            self.screen_mng.get_screen('third-screen').play_details.icon = self.play_pause.icon
            self.img.source = 'D:\\kivy mobile app\\images\\transparent.png'
            self.anim.stop(self)
        else:
            pygame.mixer.music.unpause()
            self.play_pause.icon = 'pause'
            #self.screen_mng.get_screen('third-screen').progress_details = self.progress
            #print(self.screen_mng.get_screen('third-screen').play_details.icon)
            #self.screen_mng.get_screen('third-screen').play_details.icon = self.play_pause.icon
            #print(self.screen_mng.get_screen('third-screen').play_details.icon)
            self.playing_state = False
            self.screen_mng.get_screen('third-screen').play_details.icon = self.play_pause.icon
            self.progress.start(widget)
            self.anim.start(self)
            # self.rotate()

    def stop_music(self, widget):
        self.widget = widget
        self.progress.stop(self.widget)
        pygame.mixer.music.stop()
        self.play_pause.icon = 'play-outline'
        self.is_playing = False
        self.progr.value = 0
        self.img.source = 'D:\\kivy mobile app\\images\\transparent.png'
        self.anim.stop(self)
        # self.rotate()

    def pause2(self):
        if not self.playing_state:
            pygame.mixer.music.pause()
            self.playing_state = True
        else:
            pygame.mixer.music.unpause()
            self.playing_state = False


class Tab(FloatLayout, MDTabsBase):
    pass

class ContentNavigationDrawer(MDScreen):
    pass

class MainApp(MDApp):
    def build(self):
        self.theme_cls.primary_palette = 'Blue'
        self.theme_cls.theme_style = 'Light'
        sm = ScreenManager()
        # sm.add_widget(Sounds(name='first-screen'))
        # sm.add_widget(MusicScreen(name='second-screen'))
        # sm.add_widget(Sounds(name='first-screen'))
        # sm.add_widget(MusicScreen(name='second-screen'))

        return sm

    # def on_start(self):
    #     Clock.schedule_once(self.change_screen, 10)  # Delay for 10 seconds
    #
    # ########################################################################
    # ## This function changes the current screen to main screen
    # ########################################################################
    # def change_screen(self, dt):
    #     self.root.current = "first-screen"


MainApp().run()
