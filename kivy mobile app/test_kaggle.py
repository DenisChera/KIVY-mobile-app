import csv
from PyLyrics import *
from selenium import webdriver
from selenium.webdriver.common.keys import Keys
f = open('D:\\kivy mobile app\\top50\\top100.csv')
reader = csv.reader(f)
dict_songs = {}
for row in reader:
    dict_songs[row[0]] = {'artist': row[1], 'year': row[3], 'beats_per_minute': row[4], 'energy': row[5], 'danceability': row[6], 'popularity': row[13]}

#print(dict_songs)

#print(PyLyrics.getLyrics("Ed Sheeran", "Shape of you"))

driver = webdriver.Chrome('\lyrics\chromedriver.exe')

driver.get('https://www.google.com/')

search = driver.find_elements_by_css_selector('.a4bIc')
search.send_keys('maroon5 memories lyrics')
search.send_keys(Keys.ENTER)
driver.quit()
