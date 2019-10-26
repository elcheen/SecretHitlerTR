from Constants.Cards import playerSets
from Constants.Cards import policies
import random
from Boardgamebox.State import State

class Board(object):
    def __init__(self, playercount, game):
        self.state = State()
        self.num_players = playercount
        self.fascist_track_actions = playerSets[self.num_players]["track"]
        self.policies = random.sample(playerSets[self.num_players]["policies"], len(playerSets[self.num_players]["policies"]))
        self.discards = []
        self.previous = []
   
    def print_board(self, player_sequence):
        board = "--- Liberal Tablosu ---\n"
        for i in range(5):
            if i < self.state.liberal_track:
                board += u"\u2716\uFE0F" + " " #X
            elif i >= self.state.liberal_track and i == 4:
                board += u"\U0001F54A" + " " #dove
            else:
                board += u"\u25FB\uFE0F" + " " #empty
        board += "\n--- Faşist Tablosu ---\n"
        for i in range(6):
            if i < self.state.fascist_track:
                board += u"\u2716\uFE0F" + " " #X
            else:
                action = self.fascist_track_actions[i]
                if action == None:
                    board += u"\u25FB\uFE0F" + " "  # empty
                elif action == "policy":
                    board += u"\U0001F52E" + " " # crystal
                elif action == "inspect":
                    board += u"\U0001F50E" + " " # inspection glass
                elif action == "kill":
                    board += u"\U0001F5E1" + " " # knife
                elif action == "win":
                    board += u"\u2620" + " " # skull
                elif action == "choose":
                    board += u"\U0001F454" + " " # tie

        board += "\n--- Reddedilen Seçimler ---\n"
        for i in range(3):
            if i < self.state.failed_votes:
                board += u"\u2716\uFE0F" + " " #X
            else:
                board += u"\u25FB\uFE0F" + " " #empty

        board += "\n--- Başkanlık Sırası  ---\n"        
        for player in player_sequence:
            nombre = player.name.replace("_", " ")
            if self.state.nominated_president == player:
                board += "*" + nombre + "*" + " " + u"\u27A1\uFE0F" + " "
            else:
                board += nombre + " " + u"\u27A1\uFE0F" + " "
        board = board[:-3]
        board += u"\U0001F501"
        board += "\n\nToplamda destede " + str(len(self.policies)) + " yasa kartı kaldı."
        if self.state.fascist_track >= 3:
            board += "\n\n" + u"\u203C\uFE0F" + " Dikkat: Eğer Hitler olan kişi Şansölye seçilirse, Faşistler otomatik oyunu kazanacak! " + u"\u203C\uFE0F"
        if len(self.state.not_hitlers) > 0:
            board += "\n\n Aşağıdaki oyuncuların Hitler olmadığını biliyoruz. Çünkü 3 Faşist yasa kartı tabloya koyulduktan sonra Şansölye olarak seçildiler:\n"
            for nh in self.state.not_hitlers:
                board += nh.name + ", "
            board = board[:-2]
        return board
