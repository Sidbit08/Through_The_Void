"""Private specification. Never serve this module or serialize this table."""
STAGES = {
    0: ("/index.htm", "Through the void", "ThroughTheVoid.png"),
    1: ("/level1.htm", "Linking problem!!", "Level1.jpeg"),
    2: ("/level2.htm", "Shrouded in Dark", "Level2.png"),
    3: ("/TheBrightest.htm", "Light it up", "Level3.png"),
    4: ("/Orion.htm", "The Light Falls, the Dark illuminates", "Level4.png"),
    5: ("/Hunted.htm", "A Silent Voice", "Level5.png"),
    6: ("/vivid.htm", "Echoes of the Unknown", "Level6.png"),
    7: ("/brightside.htm", "Seven In The Void", "scrambled.png"),
    8: ("/thevoid.htm", "The Winter Sky", "TheWinterSky.png"),
}
ANSWERS = {
    2: ("thelesser", "procyon"), 3: ("thebrightest", "sirius"),
    4: ("orion", "rigel"), 5: ("orion", "betelgeuse"),
    6: ("taurus", "aldebaran"), 7: ("taurus", "hyades"),
    8: ("taurus", "pleiades"),
}
ASSETS = {value[2]: stage for stage, value in STAGES.items()}
ASSETS.update({"Level5.gif": 5, "music1.mp3": 5, "hint.mp3": 6,
               "elodie_clue_4x.mp3": 1, "elodie_line2_4x.mp3": 2,
               "elodie_line3_3x.mp3": 3, "elodie_line4_3x.mp3": 4})
HINTS = {
    0: "Ahh!! So you want answers!! Try the image",
    1: "Perhaps the URL isn't how it's supposed to be??\nPassword is something before the Hound in the Night Sky\n/elodie_clue_4x.mp3",
    2: "Password is the Brightest Star in the Night Sky\n/elodie_line2_4x.mp3",
    3: "The next answer is in the image!!\n/elodie_line3_3x.mp3",
    4: "Eight steps make a letter....\n\nAs the stars emerge,\nSun dims down\nCompared to the vastness,\nIncomprehensible lengths\nIt falters greatly\n\nUsername is the same as last\n/Hunted.htm\n/elodie_line4_3x.mp3",
    5: "/Level5.png .gif me here\nSeek the name where the void began.\n/vivid.htm",
    6: "/brightside.htm\n/hint.mp3",
    7: "The image name and link seems to be connected!?\nj->k, q->w\n/thevoid.htm",
    8: "",
}
BINARY_PHRASE = "The Hunter's Red Shoulder"
HELPER_BITS = "01110010 01100111 01110111 00100000 01100001 01110111 01100011 01110111 01100010 00100000 01110110 01110111 01110100 01101001 01100010 01110011 00100000 01110010 01100111 01110111 00100000 01110110 01111001 01101011 01101011 01100001 00100000 01110111 01110100 01110111"
