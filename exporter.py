# Sauvegarde toute la base dans un fichier SQL lisible
import sqlite3

db = sqlite3.connect("projet.db")
with open("export_projet.sql", "w", encoding="utf-8") as f:
    for ligne in db.iterdump():  # CREATE TABLE puis tous les INSERT
        f.write(ligne + "\n")
db.close()
print("Export terminé : export_projet.sql")
