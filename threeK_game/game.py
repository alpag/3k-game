import abc
import random
import json
from .models import Match as mMatch, Profile

#interface kolejki FIFO
class QueueI(abc.ABC):
    @abc.abstractmethod
    def len(self):
        pass
    @abc.abstractmethod
    def pop(self):
        pass
    @abc.abstractmethod
    def push(self, value):
        pass
    @abc.abstractmethod
    def is_empty(self):
        pass
    @abc.abstractmethod
    def remove(self, object):
        pass

# klasa kolejki przechowywująca graczy, implementuje interface QueueI
# gracz - obiekt webSocket
class Queue(QueueI):
    def __init__(self, container):
        self.players = container

    def len(self):
        return len(self.players)

    def pop(self):
        return self.players.pop(0) if self.len() > 0 else None

    def push(self, value):
        self.players.append(value)

    def is_empty(self):
        return (self.len() == 0)

    def remove(self, player):
        self.players.remove(player)

    def print_content(self):
        # return tuple(self.players)
        return self.players

#singleton game manager - zarządzanie meczami
# connect_player(consumer) - metoda dołącza użytkownika do kolejki oczekujących
# create_new_game() - metoda tworzy nowy mecz usuwając graczy z kolejki oczekujących
class GameManager(object):
    __instance = None
    def __new__(cls):
        if GameManager.__instance is None:
            GameManager.__instance = object.__new__(cls)
            cls.queue = Queue([])
            cls.active_matches = []    
        return GameManager.__instance

    def connect_player(self, consumer):
        #user = consumer.scope['user'].username
        self.queue.push(consumer)
        print(self.queue.len(), end="============================ len queue\n")
        if self.queue.len() > 1:
            self.create_new_game()

    def remove_from_queue(self, consumer):
        self.queue.remove(consumer)
    
    def create_new_game(self):
        player_a = self.queue.pop()
        player_b = self.queue.pop()
        new_match= Match(player_a, player_b)
        print("match created")
        player_a._match = new_match
        player_b._match = new_match
        new_match.attach(player_a)
        new_match.attach(player_b)
        new_match.match_start = new_match.match_id
        print(new_match.match_id)
        self.active_matches.append(new_match)


# Match - klasa meczu
# wykorzystany wzorzec obserwator - gdy mecz zostanie zainicjowany, gracze zostają o tym poinformowani
# klasa łączy się z bazą oraz aktualizuje postepy meczu

class Match:
    def __init__(self, username_a, username_b):
        self.player_a = username_a
        self.player_b = username_b
        self._observers = set()
        self.create_match_model(username_a.scope['user'].username, username_b.scope['user'].username)
        self.game_list = []
        self.is_end_match = False

        self.player_a.send(text_data=json.dumps({
            'content_type': "player",
            'message': 'A'
        }))

        self.player_b.send(text_data=json.dumps({
            'content_type': "player",
            'message': 'B'
        }))

    def receive_message(self, text_data, consumer):
        if self.player_a == consumer:
            sender_is_a = True
        elif self.player_b == consumer:
            sender_is_a = False
        else:
            sender_is_a = None
            print("bugg - receive_message in match")
        
        if self.game_list[-1].is_finished == False:
            self.game_list[-1].receive_move(text_data, sender_is_a)

    def run_games(self):
        #the first win
        #create game
        #game_model = self.match_model.game_set.create()
        game_obj = Game(self)
        self.game_list.append(game_obj)

    def finish_game(self, result):
        if result == "draw":
            self.run_games()
            #end match
        else:
            self.end_match()

    def end_match(self):
        self.is_end_match = True
        print("end match")

    def disconnect(self,consumer):
        if self.is_end_match != True:
            if len(self.game_list) > 0:
                player = "A" if consumer == self.player_a else "B"
                self.game_list[-1].player_dc(player)    
            self.end_match()


    def create_match_model(self, username_a, username_b):
        print(username_a, username_b, end="---")
        user_a = Profile.objects.get(user__username=username_a)
        user_b = Profile.objects.get(user__username=username_b)
        self.match_model = mMatch.objects.create(playerA=user_a, playerB=user_b)
        self.match_id = self.match_model.id

    def attach(self, observer):
        observer._match = self
        self._observers.add(observer)

    def detach(self, observer):
        observer._match = None
        self._observers.discard(observer)

    def _notify(self):
        for observer in self._observers:
            observer.update(self._match_start)
        

    @property
    def match_start(self):
        return self._match_start

    @match_start.setter
    def match_start(self, arg):
        self._match_start = arg
        self._notify()
        self.run_games()


# klasa Game - zawiera pojedynczą instancję gry
# receive_move - odbiera posuniecia graczy
# check pattern - sprawdza stan gry
# zawiera gameHistory - wzorzec Command
class Game:
    def __init__(self, match):
        self.board = dict()
        self.is_finished = False
        self.match = match
        self.create_game_model(match.match_model)
        self.a_side = (random.random() > 0.5)
        self.group_message("New game", "log")
        self.markFactory = FlyweightFactory(Mark)
        self.gameHistory = GameHistory()
        
        self.group_message("clear", "log")
        # self.group_message("clear", "new_game")
        
        
        # self.group_message()
        
        self.group_message(json.dumps({
            'starts': 'A' if self.a_side else 'B',
            'A': self.match.player_a.scope['user'].username,
            'B': self.match.player_b.scope['user'].username,
        }), 'new_game')
        self.new_round()

    def player_dc(self, player):
        self.group_message(json.dumps({
                        'dc': 1
                    }), "finish")
        self.end_game(player)

    def receive_move(self, text_data, sender):
        text_data_json = json.loads(text_data)
        message = text_data_json['message']

        if message == "move":
            player = "A" if self.a_side else "B"
            x = text_data_json['x']
            y = text_data_json['y']
            if self.a_side == sender:
                #correct
                print("(GAME)player " + player + " make a move :" + str(x) + " " + str(y))
                if (x, y) in self.board:
                    print("(GAME) error receive move in game: mark already exists")
                    return
                self.board[(int(x), int(y))] = self.markFactory.get_instance(player)
                move_command = MoveCommand(x, y, player)
                self.gameHistory.add(move_command)
                self.group_message(json.dumps({
                    'x' : x,
                    'y' : y,
                    'player' : player,
                }), "move")

                if not self.check_pattern():
                    self.a_side = not self.a_side
                    self.new_round()
                    return
                else:
                    print("pattern is true")
            else:
                print("(GAME) error receive move in game: not your move")
                return


    def check_marks(self, a, b, c, id_pattern):
        if self.board[a].type == self.board[b].type == self.board[c].type:
            self.group_message(json.dumps({
                    'winner': self.board[a].type,
                    'pattern': id_pattern
                }), "finish")
            self.end_game(self.board[a].type)
            return True
        return False

    def check_pattern(self):
        result = 0
        print("elo in check pattern")
        if (0,0) in self.board:
            if (1,0) in self.board and (2,0) in self.board:
                # !|| patern
                result += self.check_marks((0,0), (1,0), (2,0), 0)
                    
            if (0,1) in self.board and (0,2) in self.board:
                # -.. patern
                result += self.check_marks((0,0), (0,1), (0,2), 1)
                    
            if (1,1) in self.board and (2,2) in self.board:
                # \ patern
                result += self.check_marks((0,0), (1,1), (2,2), 2)
                    
        if (1,1) in self.board:
            if (0,1) in self.board and (2,1) in self.board:
                # |!| patern
                result += self.check_marks((1,1), (0,1), (2,1), 3)
                    
            if (1,0) in self.board and (1,2) in self.board:
                # .-. patern
                result += self.check_marks((1,1), (1,0), (1,2), 4)
                    
            if (2,0) in self.board and (0,2) in self.board:
                # / patern
                result += self.check_marks((1,1), (2,0), (0,2), 5)
                    
        if (2,2) in self.board:
            if (0,2) in self.board and (1,2) in self.board:
                # ||! patern
                result += self.check_marks((2,2), (0,2), (1,2), 6)
                    
            if (2,0) in self.board and (2,1) in self.board:
                #  ..- patern
                result += self.check_marks((2,2), (2,0), (2,1), 7)
        if result > 0:
            return True 
        else:
            if len(self.board) == 9:
                self.group_message(json.dumps({
                        'draw': 1
                    }), "finish")
                self.end_game('draw')
                return True
        
        return False


    def create_game_model(self, match_model):
        self.game_model = match_model.game_set.create()

    def new_round(self):
        player = "A" if self.a_side else "B"
        self.group_message("Game is on! Player " + player + " is your move", "log")
        self.group_message(player, "turn")

    def end_game(self, result):
        self.is_finished = True
        res = 0 if result == "draw" else 1 if result == "A" else 2
        self.game_model.result = res
        moves = json.dumps(self.gameHistory.get_history())
        self.game_model.moves = moves
        self.game_model.save()
        self.match.finish_game(result)

    def group_message(self, text, content_type):
        self.match.player_a.group_message(text, content_type)


# klasa GameHistory - klasa przechowywująca ruchy graczy
# self.commands - tablica obiektow MoveCommand
class GameHistory:
    def __init__(self):
        self.commands = []
    def add(self, command):
        self.commands.append(command)
    def get_history(self):
        move_list = []
        for c in self.commands:
            move_list.append(c.execute())
        return move_list

#interface Command
class Command:
    def execute(self): pass

# MoveCommand - wzorzec Command
# Polecenie zawiera pozycje oraz gracza króry wykonał ruch
# metoda execute - zwraca zapisywalną forme ruchu
class MoveCommand(Command):
    def __init__(self, x, y, player):
        self.x = x
        self.y = y
        self.player = player    
    def execute(self):
        return { 'type': 'move', 'x': self.x, 'y': self.y, 'player': self.player}


# Tworzy i zarządza obiektami Pyłka
# Kiedy klient zapyta o obiekt(pyłek),
#                   FlyweightFactory dostarcza istniejącą instancję lub tworzy nową, jeżeli nie istnieje.
class FlyweightFactory(object):

    def __init__(self, cls):
        self._cls = cls
        self._instances = dict()

    def get_instance(self, *args, **kargs):
        return self._instances.setdefault(
                (args, tuple(kargs.items())),
                self._cls(*args, **kargs)
            )


#----------------------------------------------------------
# Objekt Mark - obiekt "pionka" w grze
# odpowiada kółkowi lub krzyżykowi
class Mark(object):
    def __init__(self, type):
        self.type = type



