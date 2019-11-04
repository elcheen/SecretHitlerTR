#!/usr/bin/env python
# -*- coding: utf-8 -*-
__author__ = "Julian Schrittwieser,  Leviatas"

import json
import logging as log
import random
import re
from random import randrange
from time import sleep

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ParseMode, Update
from telegram.ext import (Updater, CommandHandler, CallbackQueryHandler, MessageHandler, Filters, CallbackContext)


import Commands
from Constants.Cards import playerSets
from Constants.Config import TOKEN, STATS, ADMIN
from Boardgamebox.Game import Game
from Boardgamebox.Player import Player
from PlayerStats import PlayerStats
import GamesController
import datetime
import jsonpickle
import os
import psycopg2
from psycopg2 import sql
import urllib.parse

# Enable logging

log.basicConfig(
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        level=log.INFO)


logger = log.getLogger(__name__)

#DB Connection I made a Haroku Postgres database first
urllib.parse.uses_netloc.append("postgres")
url = urllib.parse.urlparse(os.environ["DATABASE_URL"])

conn = psycopg2.connect(
    database=url.path[1:],
    user=url.username,
    password=url.password,
    host=url.hostname,
    port=url.port
)
'''
cur = conn.cursor()
query = "SELECT ...."
cur.execute(query)
'''



##
#
# Beginning of round
#
##

def start_round(bot, game):        
	Commands.save_game(game.cid, "Saved Round %d" % (game.board.state.currentround + 1), game)
	log.info('start_round called')
	# Starting a new round makes the current round to go up    
	game.board.state.currentround += 1
	
	if game.board.state.chosen_president is None:
		game.board.state.nominated_president = game.player_sequence[game.board.state.player_counter]
	else:
		game.board.state.nominated_president = game.board.state.chosen_president
		game.board.state.chosen_president = None

	Commands.print_board(bot, game, game.cid)
	msgtext =  "Bir sonraki cumhurbaşkanı adayı [%s](tg://user?id=%d).\n%s, lütfen özel sohbetten bir şansölye aday gösteriniz!" % (game.board.state.nominated_president.name, game.board.state.nominated_president.uid, game.board.state.nominated_president.name)
	bot.send_message(game.cid, msgtext, ParseMode.MARKDOWN)
	choose_chancellor(bot, game)
	# --> nominate_chosen_chancellor --> vote --> handle_voting --> count_votes --> voting_aftermath --> draw_policies
	# --> choose_policy --> pass_two_policies --> choose_policy --> enact_policy --> start_round


def choose_chancellor(bot, game):
	log.info('choose_chancellor called')
	strcid = str(game.cid)
	pres_uid = 0
	chan_uid = 0
	btns = []
	if game.board.state.president is not None:
		pres_uid = game.board.state.president.uid
	if game.board.state.chancellor is not None:
		chan_uid = game.board.state.chancellor.uid
	for uid in game.playerlist:
		# If there are only five players left in the
		# game, only the last elected Chancellor is
		# ineligible to be Chancellor Candidate; the
		# last President may be nominated.
		if len(game.player_sequence) > 5:
			if uid != game.board.state.nominated_president.uid and game.playerlist[uid].is_dead == False and uid != pres_uid and uid != chan_uid:
				name = game.playerlist[uid].name
				btns.append([InlineKeyboardButton(name, callback_data=strcid + "_chan_" + str(uid))])
		else:
			if uid != game.board.state.nominated_president.uid and game.playerlist[uid].is_dead == False and uid != chan_uid:
				name = game.playerlist[uid].name
				btns.append([InlineKeyboardButton(name, callback_data=strcid + "_chan_" + str(uid))])

	chancellorMarkup = InlineKeyboardMarkup(btns)
	#descomentar al entrar en produccion

	if game.is_debugging:
		Commands.print_board(bot, game, ADMIN)
		bot.send_message(ADMIN, 'Por favor nomina a tu canciller!', reply_markup=chancellorMarkup)      
	else:
		Commands.print_board(bot, game, game.board.state.nominated_president.uid)
		groupName = ""
		if hasattr(game, 'groupName'):
			groupName += "*Grup Bilgisi: {}*\n".format(game.groupName)
		msg = '{}Lütfen Şansölye adayınızı seçin'.format(groupName)
		bot.send_message(game.board.state.nominated_president.uid, msg, reply_markup=chancellorMarkup)

	game.board.state.fase = "choose_chancellor"
	Commands.save_game(game.cid, "choose_chancellor Round %d" % (game.board.state.currentround), game)

def nominate_chosen_chancellor(update: Update, context: CallbackContext):
	bot = context.bot
	log.info('nominate_chosen_chancellor called')
	log.info(update.callback_query.data)
	callback = update.callback_query
	regex = re.search("(-[0-9]*)_chan_([0-9]*)", callback.data)
	cid = int(regex.group(1))
	chosen_uid = int(regex.group(2))
	#if(game.is_debugging):
	#    chosen_uid = ADMIN   
	try:
		game = Commands.get_game(cid)

		if callback.from_user.id != game.board.state.nominated_president.uid:
			bot.edit_message_text("Şu anki başkan sen değilsin, aday gösteremezsin", callback.from_user.id, callback.message.message_id)
			return

		game.board.state.nominated_chancellor = game.playerlist[chosen_uid]
		log.info("El Presidente %s (%d) nominó a %s (%d)" % (
					game.board.state.nominated_president.name, game.board.state.nominated_president.uid,
					game.board.state.nominated_chancellor.name, game.board.state.nominated_chancellor.uid))
		bot.edit_message_text("Şansölye olarak %s'ı aday gösterdiniz!" % game.board.state.nominated_chancellor.name,
					callback.from_user.id, callback.message.message_id)
		bot.send_message(game.cid,
					"Başkan %s, %s'ı şansölye olarak aday gösterdi. Lütfen oy verin!" % (
					game.board.state.nominated_president.name, game.board.state.nominated_chancellor.name))
		vote(bot, game)
		# Save after voting buttons send and set phase voting
		game.board.state.fase = "vote"
		Commands.save_game(game.cid, "Oy Zamanı %d" % (game.board.state.currentround), game)
	except AttributeError as e:
		log.error("nominate_chosen_chancellor: Game or board should not be None! Eror: " + str(e))
	except Exception as e:
		log.error("Unknown error: " + repr(e))
		log.exception(e)
		
def vote(bot, game):
	log.info('vote called')
	#When voting starts we start the counter to see later with the vote command if we can see you voted.
	game.dateinitvote = datetime.datetime.now()

	strcid = str(game.cid)
	btns = [[InlineKeyboardButton("Evet", callback_data=strcid + "_Ja"),
	InlineKeyboardButton("Hayır", callback_data=strcid + "_Nein")]]
	voteMarkup = InlineKeyboardMarkup(btns)
	for uid in game.playerlist:
		if not game.playerlist[uid].is_dead and not game.is_debugging:
			if game.playerlist[uid] is not game.board.state.nominated_president:
				# the nominated president already got the board before nominating a chancellor
				Commands.print_board(bot, game, uid)
			groupName = ""		
			if hasattr(game, 'groupName'):
				groupName += "*Grup Bilgisi: {}*\n".format(game.groupName)
			msg = "{}Başkanın *{}* ve Şansölyenin *{}* olmasınk onaylıyor musun?".format(groupName, game.board.state.nominated_president.name, game.board.state.nominated_chancellor.name)
			bot.send_message(uid, msg,	reply_markup=voteMarkup, parse_mode=ParseMode.MARKDOWN)


def handle_voting(update: Update, context: CallbackContext):
	bot = context.bot
	callback = update.callback_query
	log.info('handle_voting called: %s' % callback.data)
	regex = re.search("(-[0-9]*)_(.*)", callback.data)
	cid = int(regex.group(1))
	answer = regex.group(2)
	strcid = regex.group(1)
	try:
		game = Commands.get_game(cid)
		uid = callback.from_user.id
		#
		if game.dateinitvote is None:
			bot.edit_message_text("Oy verme zamanı değil!", uid, callback.message.message_id)
			return

		bot.edit_message_text("Oyunuz kaydedildi: %s Başkan %s ve Şansölye %s için" % (
			answer, game.board.state.nominated_president.name, game.board.state.nominated_chancellor.name), uid,
			callback.message.message_id)
		log.info("Player %s (%d) voted %s" % (callback.from_user.first_name, uid, answer))

		#if uid not in game.board.state.last_votes:
		game.board.state.last_votes[uid] = answer

		#Allow player to change his vote
		btns = [[InlineKeyboardButton("Evet", callback_data=strcid + "_Ja"),
				InlineKeyboardButton("Hayır", callback_data=strcid + "_Nein")]]
		voteMarkup = InlineKeyboardMarkup(btns)
		 
		groupName = ""
		
		if hasattr(game, 'groupName'):
			groupName += "*Grup Bilgisi {}*\n".format(game.groupName)

		msg = "{}\nOyunuzu tekrar değiştirebilirsiniz.\nCumhurbaşkanı *{}* ve Şansöyle *{}*'ı onaylıyor musun?".format(groupName, game.board.state.nominated_president.name, game.board.state.nominated_chancellor.name)
		bot.send_message(uid, msg, reply_markup=voteMarkup, parse_mode=ParseMode.MARKDOWN)
		Commands.save_game(game.cid, "vote Round %d" % (game.board.state.currentround), game)
		if len(game.board.state.last_votes) == len(game.player_sequence):
			count_votes(bot, game)
	except Exception as e:
		log.error(str(e))

def count_votes(bot, game):
	# La votacion ha finalizado.
	game.dateinitvote = None
	# La votacion ha finalizado.
	log.info('count_votes called')
	voting_text = ""
	voting_success = False
	for player in game.player_sequence:
		nombre_jugador = game.playerlist[player.uid].name.replace("_", " ")
		if game.board.state.last_votes[player.uid] == "Ja":
			voting_text += nombre_jugador + " 'ın oyu Evet!\n"
		elif game.board.state.last_votes[player.uid] == "Nein":
			voting_text += nombre_jugador + " 'ın oyu Hayır!\n"
	if list(game.board.state.last_votes.values()).count("Ja") > (
		len(game.player_sequence) / 2):  # because player_sequence doesnt include dead
		# VOTING WAS SUCCESSFUL
		log.info("Voting successful")
		voting_text += "Heil Başkan [%s](tg://user?id=%d)! Heil Şansölye [%s](tg://user?id=%d)!" % (
			game.board.state.nominated_president.name, game.board.state.nominated_president.uid, 
				game.board.state.nominated_chancellor.name, game.board.state.nominated_chancellor.uid)
		game.board.state.chancellor = game.board.state.nominated_chancellor
		game.board.state.president = game.board.state.nominated_president
		game.board.state.nominated_president = None
		game.board.state.nominated_chancellor = None
		voting_success = True
		
		bot.send_message(game.cid, voting_text, ParseMode.MARKDOWN)
		bot.send_message(game.cid, "\nYasa koyulana kadar hükümet konuşamaz.")
		game.history.append(("Ronda %d.%d\n\n" % (game.board.state.liberal_track + game.board.state.fascist_track + 1, game.board.state.failed_votes + 1) ) + voting_text)
		#log.info(game.history[game.board.state.currentround])
		voting_aftermath(bot, game, voting_success)
	else:
		log.info("Voting failed")
		voting_text += "Halk, Başkanın %s ve Şansölyenin %s olacağı hükümeti beğenmedi!" % (
			game.board.state.nominated_president.name, game.board.state.nominated_chancellor.name)
		game.board.state.nominated_president = None
		game.board.state.nominated_chancellor = None
		game.board.state.failed_votes += 1
		bot.send_message(game.cid, voting_text)
		game.history.append(("Ronda %d.%d\n\n" % (game.board.state.liberal_track + game.board.state.fascist_track + 1, game.board.state.failed_votes) ) + voting_text)
		#log.info(game.history[game.board.state.currentround])
		if game.board.state.failed_votes == 3:
			do_anarchy(bot, game)
		else:
			voting_aftermath(bot, game, voting_success)


def voting_aftermath(bot, game, voting_success):
	log.info('voting_aftermath called')
	game.board.state.last_votes = {}
	if voting_success:
		if game.board.state.fascist_track >= 3 and game.board.state.chancellor.role == "Hitler":
			# fascists win, because Hitler was elected as chancellor after 3 fascist policies
			game.board.state.game_endcode = -2
			end_game(bot, game, game.board.state.game_endcode)
		else:
			if game.board.state.fascist_track >= 3 and game.board.state.chancellor.role != "Hitler" and game.board.state.chancellor not in game.board.state.not_hitlers:
				game.board.state.not_hitlers.append(game.board.state.chancellor)
			# voting was successful and Hitler was not nominated as chancellor after 3 fascist policies
			draw_policies(bot, game)
	else:
		#Commands.print_board(bot, game, game.cid)
		start_next_round(bot, game)


def draw_policies(bot, game):
	log.info('draw_policies called')
	strcid = str(game.cid)
	game.board.state.veto_refused = False
	# shuffle discard pile with rest if rest < 3
	shuffle_policy_pile(bot, game)
	btns = []
	hiddenhistory_text = ""
	for i in range(3):
		game.board.state.drawn_policies.append(game.board.policies.pop(0))
	for policy in game.board.state.drawn_policies:
		btns.append([InlineKeyboardButton(policy, callback_data=strcid + "_" + policy)])
		hiddenhistory_text += policy.title() + " "
	hiddenhistory_text[:-1]
	# Guardo Historial secreto
	game.hiddenhistory.append(("*Ronda %d.%d*\nEl presidente %s recibió " % (game.board.state.liberal_track + game.board.state.fascist_track + 1, game.board.state.failed_votes + 1, game.board.state.president.name) ) + hiddenhistory_text)
	choosePolicyMarkup = InlineKeyboardMarkup(btns)
	if not game.is_debugging:
		bot.send_message(game.board.state.president.uid, "Aşağıdaki 3 yasayı desteden çektin. Hangisini çöpe atmak istersin?",
			reply_markup=choosePolicyMarkup)
	else:
		bot.send_message(ADMIN, "Aşağıdaki 3 yasayı desteden çektin. Hangisini çöpe atmak istersin?",
			reply_markup=choosePolicyMarkup)
	game.board.state.fase = "legislating president discard"
	Commands.save_game(game.cid, "legislating president discard Round %d" % (game.board.state.currentround), game)

def choose_policy(update: Update, context: CallbackContext):
	bot = context.bot
	log.info('choose_policy called')
	callback = update.callback_query
	regex = re.search("(-[0-9]*)_(.*)", callback.data)
	cid = int(regex.group(1))
	answer = regex.group(2)
	try:
		game = Commands.get_game(cid)	
		strcid = str(game.cid)
		uid = callback.from_user.id

		# Solo el presidente y el canciller pueden elegir politica.
		if uid not in [game.board.state.chancellor.uid, game.board.state.president.uid]:
			msg = "Şu an Başkan ya da Şansölye değilsin!"
			bot.edit_message_text(msg, uid,	callback.message.message_id)
			return

		# Si hay 3 politicas veo que sea el presidente el que descarte.
		if len(game.board.state.drawn_policies) == 3 and uid == game.board.state.president.uid:
			log.info("Player %s (%d) discarded %s" % (callback.from_user.first_name, uid, answer))
			bot.edit_message_text("%s yasası atılacak!" % answer, uid,
			callback.message.message_id)
			# remove policy from drawn cards and add to discard pile, pass the other two policies
			# Grabo en Hidden History que descarta el presidente.
			game.hiddenhistory.append("Başkan yasa elemesi yaptı " + answer)
			for i in range(3):
				if game.board.state.drawn_policies[i] == answer:
					game.board.discards.append(game.board.state.drawn_policies.pop(i))                                
					break
			pass_two_policies(bot, game)
		elif len(game.board.state.drawn_policies) == 2 and uid == game.board.state.chancellor.uid:
			# Si el canciller elije el boton de veto
			if answer == "veto" :
				log.info("Player %s (%d) suggested a veto" % (callback.from_user.first_name, uid))
				bot.edit_message_text("Başkan %s'a veto önerdin" % game.board.state.president.name, uid,
					callback.message.message_id)
				bot.send_message(game.cid,
					"Şansölye %s, Başkan %s'a veto önerdi." % (
					game.board.state.chancellor.name, game.board.state.president.name))

				btns = [[InlineKeyboardButton("Veto! (öneri kabul edildi)", callback_data=strcid + "_yesveto")],
				[InlineKeyboardButton("Veto İptal! (önerin reddedildi)", callback_data=strcid + "_noveto")]]

				vetoMarkup = InlineKeyboardMarkup(btns)
				bot.send_message(game.board.state.president.uid,
					"Şansölye %s veto etmeyi önerdi. Bu kartları veto (iptal) etmek ister misin?" % game.board.state.chancellor.name,
					reply_markup=vetoMarkup)
			else:
				# Si el canciller promulga...
				log.info("Player %s (%d) chose a %s policy" % (callback.from_user.first_name, uid, answer))
				bot.edit_message_text("%s yasası onaylanacak!" % answer, uid,
				callback.message.message_id)
				# remove policy from drawn cards and enact, discard the other card
				for i in range(2):
					if game.board.state.drawn_policies[i] == answer:
						game.board.state.drawn_policies.pop(i)
						break
				game.board.discards.append(game.board.state.drawn_policies.pop(0))
				assert len(game.board.state.drawn_policies) == 0
				enact_policy(bot, game, answer, False)
		else:
			log.error("choose_policy: drawn_policies should be 3 or 2, but was " + str(
				len(game.board.state.drawn_policies)))
	except Exception as e:
		log.error("choose_policy:" + str(e))

def pass_two_policies(bot, game):
	log.info('pass_two_policies called')
	strcid = str(game.cid)
	btns = []
	for policy in game.board.state.drawn_policies:
		btns.append([InlineKeyboardButton(policy, callback_data=strcid + "_" + policy)])
	if game.board.state.fascist_track == 5 and not game.board.state.veto_refused:
		btns.append([InlineKeyboardButton("Veto", callback_data=strcid + "_veto")])
		choosePolicyMarkup = InlineKeyboardMarkup(btns)
		bot.send_message(game.cid,
			"Başkan %s, Şansölye %s'a 2 yasa verdi." % (
			game.board.state.president.name, game.board.state.chancellor.name))
		bot.send_message(game.board.state.chancellor.uid,
			"Başkan %s, size bu 2 yasayı verdi. Hangisini onaylamak istiyorsunuz? Veto önerisi sunabilirsin." % game.board.state.president.name,
		reply_markup=choosePolicyMarkup)
	elif game.board.state.veto_refused:
		choosePolicyMarkup = InlineKeyboardMarkup(btns)
		bot.send_message(game.board.state.chancellor.uid,
			"Başkan %s, Veto önerinizi reddetti. Şimdi seçmek zorundasın. Hangi yasayı onaylamak istiyorsunuz?" % game.board.state.president.name,
			reply_markup=choosePolicyMarkup)
	elif game.board.state.fascist_track < 5:
		bot.send_message(game.cid,
			"Başkan %s, Şansölye %s'a 2 yasa verdi." % (
			game.board.state.president.name, game.board.state.chancellor.name))
		choosePolicyMarkup = InlineKeyboardMarkup(btns)
		if not game.is_debugging:
			bot.send_message(game.board.state.chancellor.uid,
				"Başkan %s, size bu 2 yasayı verdi. Hangisini onaylamak istiyorsunuz?" % game.board.state.president.name,
				reply_markup=choosePolicyMarkup)
		else:
			bot.send_message(ADMIN,
				"Başkan %s, size bu 2 yasayı verdi. Hangisini onaylamak istiyorsunuz?" % game.board.state.president.name,
				reply_markup=choosePolicyMarkup)	
	
	game.board.state.fase = "legislating choose chancellor"
	Commands.save_game(game.cid, "legislating choose chancellor Round %d" % (game.board.state.currentround), game)

def enact_policy(bot, game, policy, anarchy):
	log.info('enact_policy called')
	if policy == "liberal":
		game.board.state.liberal_track += 1
	elif policy == "fascista":
		game.board.state.fascist_track += 1
	game.board.state.failed_votes = 0  # reset counter
	if not anarchy:
		bot.send_message(game.cid, "Başkan %s ve Şansölye %s'nin onayladığı yasa %s!" % (game.board.state.president.name, game.board.state.chancellor.name, policy))
		game.history.append("Başkan %s ve Şansölye %s'nin onayladığı yasa %s!" % (game.board.state.president.name, game.board.state.chancellor.name, policy))
	else:
		bot.send_message(game.cid, "Destenin en üstündeki kart olan %s yasası tabloya eklendi" % policy)
		game.history.append("Destenin en üstündeki kart olan %s yasası tabloya eklendi" % policy)
	#sleep(2)    
	# end of round
	if game.board.state.liberal_track == 5:
		game.board.state.game_endcode = 1
		end_game(bot, game, game.board.state.game_endcode)  # liberals win with 5 liberal policies
	if game.board.state.fascist_track == 6:
		game.board.state.game_endcode = -1
		end_game(bot, game, game.board.state.game_endcode)  # fascists win with 6 fascist policies
	#sleep(3)
	# End of legislative session, shuffle if necessary 
	shuffle_policy_pile(bot, game)    
	if not anarchy:
		if policy == "fascista":
			action = game.board.fascist_track_actions[game.board.state.fascist_track - 1]
			if action is None and game.board.state.fascist_track == 6:
				pass
			elif action == None:
				start_next_round(bot, game)
			elif action == "policy":
				bot.send_message(game.cid,
					"Cumhurbaşkanı gücü açıldı: Yasaları Görme " + u"\U0001F52E" + "\nBaşkan %s, kart destesinin en üstündeki 3 kartı görecek"
					" Başkan bunu diğer oyuncularla paylaşabilir"
					" (ya da yalan söyleyebilir!) sonuçlarına herkes katlanır "
					" Akıllıca seçim yap.." % game.board.state.president.name)
				game.history.append("Başkan %s, şimdi gelecek 3 yasa kartının ne olduğunu biliyor." % game.board.state.president.name)
				action_policy(bot, game)                
			elif action == "kill":
				msg = "Cumhurbaşkanı gücü açıldı: İnfaz " + u"\U0001F5E1" + "\nBaşkan %s, bir kişi öldürmek zorunda. Kararı tartışabilirsiniz ancak unutmayın son sözü Başkan söyler!" % game.board.state.president.name
				bot.send_message(game.cid, msg)
				game.board.state.fase = "legislating power kill"
				Commands.save_game(game.cid, "legislating power kill Round %d" % (game.board.state.currentround), game)
				action_kill(bot, game)				
			elif action == "inspect":
				bot.send_message(game.cid,
					"Cumhurbaşkanı gücü açıldı: Parti Üyeliği Görme " + u"\U0001F50E" + "\nBaşkan %s, bir kişinin parti üyeliğini görebilecek"
					" Başkan bunu diğerleriyle paylaşabilir"
					" (ya da yalan söyleyebilir!) sonuçlarına herkes katlanır"
					" Seçimini akıllıca yap.." % game.board.state.president.name)
				game.board.state.fase = "legislating power inspect"
				Commands.save_game(game.cid, "legislating power inspect Round %d" % (game.board.state.currentround), game)				
				action_inspect(bot, game)
			elif action == "choose":
				bot.send_message(game.cid,
					"Cumhurbaşkanı gücü açıldı: Başkan Atama Yetkisi " + u"\U0001F454" + "\nBaşkan %s, bir sonraki başkanın kim olacağını seçebilecek."
					" Daha sonra seçim kaldığı yerden"
					" devam edecektir." % game.board.state.president.name)
				game.board.state.fase = "legislating power choose"
				Commands.save_game(game.cid, "legislating power choose Round %d" % (game.board.state.currentround), game)
				action_choose(bot, game)
		else:
			start_next_round(bot, game)
	else:
		start_next_round(bot, game)


def choose_veto(update: Update, context: CallbackContext):
	
    bot = context.bot

    callback = update.callback_query
    regex = re.search("(-[0-9]*)_(.*)", callback.data)
    cid = int(regex.group(1))
    answer = regex.group(2)
    try:
        game = Commands.get_game(cid)
        uid = callback.from_user.id
        if answer == "yesveto":
            log.info("Player %s (%d) accepted the veto" % (callback.from_user.first_name, uid))
            bot.edit_message_text("Veto kabul edildi!", uid, callback.message.message_id)
            bot.send_message(game.cid,
                             "Başkan %s, Şansölyesi %s'ın yapmış olduğu veto teklifini kabul etti. Hiçbir yasa yürürlülüğe girmeyecek ancak bu bir başarısız seçim olarak işaretlenecek." % (
                                 game.board.state.president.name, game.board.state.chancellor.name))
            game.board.discards += game.board.state.drawn_policies
            game.board.state.drawn_policies = []
            game.board.state.failed_votes += 1
            shuffle_policy_pile(bot, game)  
            if game.board.state.failed_votes == 3:
                do_anarchy(bot, game)
            else:                
                start_next_round(bot, game)
        elif answer == "noveto":
            log.info("Player %s (%d) declined the veto" % (callback.from_user.first_name, uid))
            game.board.state.veto_refused = True
            bot.edit_message_text("Veto reddedildi!", uid, callback.message.message_id)
            bot.send_message(game.cid,
                             "Başkan %s, Şansölyesi %s'ın veto teklifini reddetti. Şansölye şimdi yürürlülüğe bir yasa koymak zorunda!" % (
                                 game.board.state.president.name, game.board.state.chancellor.name))
            pass_two_policies(bot, game)
        else:
            log.error("choose_veto: Callback data can either be \"veto\" or \"noveto\", but not %s" % answer)
    except:
        log.error("choose_veto: Game or board should not be None!")


def do_anarchy(bot, game):
	#log.info('do_anarchy called')	
	bot.send_message(game.cid, "ANARŞİİ!!")
	game.board.state.president = None
	game.board.state.chancellor = None
	top_policy = game.board.policies.pop(0)
	game.board.state.last_votes = {}
	enact_policy(bot, game, top_policy, True)


def action_policy(bot, game):
    log.info('action_policy called')
    topPolicies = ""
    # shuffle discard pile with rest if rest < 3
    shuffle_policy_pile(bot, game)
    for i in range(3):
        topPolicies += game.board.policies[i] + "\n"
    bot.send_message(game.board.state.president.uid,
                     "Sonraki 3 yasa (üst sıralamasına göre):\n%s\nPaylaşmamayı seçebilirsiniz." % topPolicies)
    start_next_round(bot, game)


def action_kill(bot, game):
	log.info('action_kill called')
	strcid = str(game.cid)
	btns = []
	for uid in game.playerlist:
		if uid != game.board.state.president.uid and game.playerlist[uid].is_dead == False:
			name = game.playerlist[uid].name
			btns.append([InlineKeyboardButton(name, callback_data=strcid + "_kill_" + str(uid))])

	killMarkup = InlineKeyboardMarkup(btns)
	Commands.print_board(bot, game, game.board.state.president.uid)
	bot.send_message(game.board.state.president.uid,
		'Birini öldürmek zorundasın. Kararını diğerleri ile tartışabilirsin. Akıllıca seç!',
		reply_markup=killMarkup)


def choose_kill(update: Update, context: CallbackContext):
	
    bot = context.bot
    callback = update.callback_query
    regex = re.search("(-[0-9]*)_kill_(.*)", callback.data)
    cid = int(regex.group(1))
    answer = int(regex.group(2))
    try:
        game = Commands.get_game(cid)
        chosen = game.playerlist[answer]
        chosen.is_dead = True
        if game.player_sequence.index(chosen) <= game.board.state.player_counter:
            game.board.state.player_counter -= 1
        game.player_sequence.remove(chosen)
        game.board.state.dead += 1
        log.info("El jugador %s (%d) mató a %s (%d)" % (
            callback.from_user.first_name, callback.from_user.id, chosen.name, chosen.uid))
        bot.edit_message_text("%s'ı öldürdün!" % chosen.name, callback.from_user.id, callback.message.message_id)
        if chosen.role == "Hitler":
            bot.send_message(game.cid, "Başkan " + game.board.state.president.name + " 'ı öldürdü " + chosen.name + ". ")
            end_game(bot, game, 2)
        else:
            bot.send_message(game.cid,
                             "Başkan %s, %s’ı öldürdü ve o Hitler değildi. %s, şu andan itibaren ölüsün ve ölüler konuşamaz!" % (
                                 game.board.state.president.name, chosen.name, chosen.name))
            
            game.history.append("Başkan %s, %s’ı öldürdü ve o Hitler değildi." % (game.board.state.president.name, chosen.name))
            start_next_round(bot, game)
    except:
        log.error("choose_kill: Game or board should not be None!")


def action_choose(bot, game):
    log.info('action_choose called')
    strcid = str(game.cid)
    btns = []

    for uid in game.playerlist:
        if uid != game.board.state.president.uid and game.playerlist[uid].is_dead == False:
            name = game.playerlist[uid].name
            btns.append([InlineKeyboardButton(name, callback_data=strcid + "_choo_" + str(uid))])

    inspectMarkup = InlineKeyboardMarkup(btns)
    Commands.print_board(bot, game, game.board.state.president.uid)
    bot.send_message(game.board.state.president.uid,
                     'Bir sonraki başkanı seçebileceksin. Daha sonra sıralama normale döner.',
                     reply_markup=inspectMarkup)


def choose_choose(update: Update, context: CallbackContext):
	
    bot = context.bot
    callback = update.callback_query
    regex = re.search("(-[0-9]*)_choo_(.*)", callback.data)
    cid = int(regex.group(1))
    answer = int(regex.group(2))
    try:
        game = Commands.get_game(cid)
        chosen = game.playerlist[answer]
        game.board.state.chosen_president = chosen
        log.info(
            "El jugador %s (%d) ha elegido a %s (%d) como próximo Presidente" % (
                callback.from_user.first_name, callback.from_user.id, chosen.name, chosen.uid))
        bot.edit_message_text("%s’ı bir sonraki başkan seçtin!" % chosen.name, callback.from_user.id,
                              callback.message.message_id)
        bot.send_message(game.cid,
                         "Başkan %s’ın başkanlık seçimi %s." % (
                             game.board.state.president.name, chosen.name))
        game.history.append("Başkan %s’ın başkanlık seçimi %s." % (game.board.state.president.name, chosen.name))
        start_next_round(bot, game)
    except:
        log.error("choose_choose: Game or board should not be None!")


def action_inspect(bot, game):
    log.info('action_inspect called')
    strcid = str(game.cid)
    btns = []
    for uid in game.playerlist:
        if uid != game.board.state.president.uid and game.playerlist[uid].is_dead == False and game.playerlist[uid].was_investigated == False:
            name = game.playerlist[uid].name
            btns.append([InlineKeyboardButton(name, callback_data=strcid + "_insp_" + str(uid))])

    inspectMarkup = InlineKeyboardMarkup(btns)
    Commands.print_board(bot, game, game.board.state.president.uid)
    bot.send_message(game.board.state.president.uid,
                     'Bir kişinin parti üyeliğini görebileceksin. Kimi seçmek istersin. İyi düşün!',
                     reply_markup=inspectMarkup)


def choose_inspect(update: Update, context: CallbackContext):
	
    bot = context.bot
    callback = update.callback_query
    regex = re.search("(-[0-9]*)_insp_(.*)", callback.data)
    cid = int(regex.group(1))
    answer = int(regex.group(2))
    try:
        game = Commands.get_game(cid)
        chosen = game.playerlist[answer]
        log.info(
            "Player %s (%d) inspects %s (%d)'s party membership (%s)" % (
                callback.from_user.first_name, callback.from_user.id, chosen.name, chosen.uid,
                chosen.party))
        bot.edit_message_text("%s‘ın parti üyeliği %s" % (chosen.name, chosen.party),
                              callback.from_user.id,
                              callback.message.message_id)
        chosen.was_investigated = True
        bot.send_message(game.cid, "Başkan %s, %s’ı dikizledi." % (game.board.state.president.name, chosen.name))
        game.history.append("Başkan %s, %s’ı dikizledi." % (game.board.state.president.name, chosen.name))
        start_next_round(bot, game)
    except:
        log.error("choose_inspect: Game or board should not be None!")


def start_next_round(bot, game):
    log.info('start_next_round called')
    # start next round if there is no winner (or /cancel)
    if game.board.state.game_endcode == 0:
        # start new round
        sleep(5)
        # if there is no special elected president in between
        if game.board.state.chosen_president is None:
            increment_player_counter(game)
        start_round(bot, game)


def decide_anarquia(bot, game):
	log.info('decide_anarquia called')
	#When voting starts we start the counter to see later with the vote command if we can see you voted.
	game.board.state.votes_anarquia = {}
	strcid = str(game.cid)
	btns = [[InlineKeyboardButton("Evet", callback_data=strcid + "_SiAna"),
	InlineKeyboardButton("Hayır", callback_data=strcid + "_NoAna")]]
	voteMarkup = InlineKeyboardMarkup(btns)
	for uid in game.playerlist:
		if not game.is_debugging:
			if not game.playerlist[uid].is_dead:                      
				Commands.print_board(bot, game, uid)				
				bot.send_message(uid, "Anarşiye gitmek ister misin? (Eğer oyuncuların yarısı gitmeyi seçerse)", reply_markup=voteMarkup)
		else:
			bot.send_message(ADMIN, game.board.print_board(game.player_sequence))
			bot.send_message(ADMIN, "Anarşiye gitmek ister misin? (Eğer oyuncuların gitmeyi seçerse kabul edilir", reply_markup=voteMarkup)
			
def handle_voting_anarquia(update: Update, context: CallbackContext):
	bot = context.bot
	callback = update.callback_query
	log.info('handle_voting_anarquia called: %s' % callback.data)
	regex = re.search("(-[0-9]*)_(.*)", callback.data)
	cid = int(regex.group(1))
	answer = regex.group(2)
	strcid = regex.group(1)
	try:
		game = Commands.get_game(cid)
		uid = callback.from_user.id
		answer = answer.replace("Ana", "")
		bot.edit_message_text("Oy verdiğiniz için teşekkürler: Anarşiye %s " % (answer), uid, callback.message.message_id)
		log.info("Player %s (%d) voted %s" % (callback.from_user.first_name, uid, answer))

		#if uid not in game.board.state.last_votes:
		game.board.state.votes_anarquia[uid] = answer
		
		if game.is_debugging:
			for uid in game.playerlist:
				if not game.playerlist[uid].is_dead:
					game.board.state.votes_anarquia[uid] = answer			

		#Allow player to change his vote
		btns = [[InlineKeyboardButton("Evet", callback_data=strcid + "_JaAna"),
		InlineKeyboardButton("Hayır", callback_data=strcid + "_NeinAna")]]
		voteMarkup = InlineKeyboardMarkup(btns)
		bot.send_message(uid, "Puedes cambiar tu voto aquí.\n¿Quieres ir a anarquia? (CUIDADO si la mitad de los jugadores elige SI no se espera)", reply_markup=voteMarkup)
		
		if len(game.board.state.votes_anarquia) == len(game.player_sequence):
			count_votes_anarquia(bot, game)
		'''elif list(game.board.state.votes_anarquia.values()).count("Si") >= (len(game.player_sequence) / 2):
			# Caso especial si ya la mitad o mas de los jugadores decidio ir a anarquia se va no más.
			count_votes_anarquia(bot, game)
		'''
	except Exception as e:
		log.error(str(e))

def count_votes_anarquia(bot, game):
	# La votacion ha finalizado.
	game.dateinitvote = None
	# La votacion ha finalizado.
	log.info('count_votes_anarquia called')
	voting_text = ""
	voting_success = False
	for player in game.player_sequence:
		nombre_jugador = game.playerlist[player.uid].name
		if game.board.state.votes_anarquia[player.uid] == "Si":
			voting_text += nombre_jugador + " Evet oyu verdi!\n"
		elif game.board.state.votes_anarquia[player.uid] == "No":
			voting_text += nombre_jugador + " Hayır oyu verdi!\n"
	if list(game.board.state.votes_anarquia.values()).count("Si") >= (len(game.player_sequence) / 2):  # because player_sequence doesnt include dead
		# VOTING WAS SUCCESSFUL
		log.info("Anarşi kazandı!")
		voting_text += "Oyuncuların çoğu anarşiye gitmeye karar verdiğinden, anarşi yürütülecek."		
		game.board.state.nominated_president = None
		game.board.state.nominated_chancellor = None
		bot.send_message(game.cid, voting_text, ParseMode.MARKDOWN)
		bot.send_message(game.cid, "\nŞimdi konuşamazsın.")
		game.history.append(("Ronda %d.%d\n\n" % (game.board.state.liberal_track + game.board.state.fascist_track + 1, game.board.state.failed_votes + 1) ) + voting_text)
		# Avanzo la cantidad del lider asi el lider queda correctamente asignado
		# Se incrementa como mucho 2 ya que el ultimo incremento lo hace la anarquia
		for i in range(2 - game.board.state.failed_votes):
			increment_player_counter(game)		
		do_anarchy(bot, game)
	else:
		log.info("Halk anarşiyi istemiyor")
		voting_text += "Halk anarşiyi istemiyor"
		game.board.state.nominated_president = None
		game.board.state.nominated_chancellor = None
		bot.send_message(game.cid, voting_text, ParseMode.MARKDOWN)
		game.history.append(("Ronda %d.%d\n\n" % (game.board.state.liberal_track + game.board.state.fascist_track + 1, game.board.state.failed_votes + 1) ) + voting_text)
		#game.board.state.failed_votes == 3
		
			
##
#
# End of round
#
##

def get_stats(bot, cid):
	try:
		cur = conn.cursor()
		query = "select * from stats"
		cur.execute(query)
		dbdata = cur.fetchone()
		return dbdata
	except Exception as e:
		bot.send_message(cid, 'No se ejecuto el comando get_stats debido a: '+str(e))
		conn.rollback()	

def set_stats(column_name, value, bot, cid):
	try:
		cursor = conn.cursor()
		#cursor.execute("UPDATE stats SET %s=%s", (column_name, value));		
		cursor.execute(sql.SQL("UPDATE stats set {}=%s ").format(sql.Identifier(column_name)), [value])
		
		conn.commit()
	except Exception as e:
		bot.send_message(cid, 'No se ejecuto el comandoset_stats debido a: '+str(e))
		conn.rollback()
		
def save_game_details(bot, print_roles, game_endcode, liberal_track, fascist_track, num_players):
	try:
		#Check if game is in DB first
		cursor = conn.cursor()			
		log.info("Executing in DB")		
		query = "INSERT INTO stats_detail(playerlist, game_endcode, liberal_track, fascist_track, num_players) VALUES (%s, %s, %s, %s, %s);"
		#query = "INSERT INTO games(id , groupName  , data) VALUES (%s, %s, %s) RETURNING data;"
		cursor.execute(query, (print_roles, game_endcode, liberal_track, fascist_track, num_players))		
		#dbdata = cur.fetchone()
		conn.commit()
	except Exception as e:
		conn.rollback()
		bot.send_message(ADMIN, 'No se ejecuto el comando save_game_details debido a: '+str(e))

def change_stats(uid, tipo_juego, stat_name, amount):
	user_stats = load_player_stats(uid)		
	# Si no tiene registro, lo creo
	if user_stats is None:
		user_stats = PlayerStats(uid)	
	user_stats.change_data_stat(tipo_juego, stat_name, amount)
	save_player_stats(uid, user_stats)	

def save_player_stats(uid, data):
	#Check if game is in DB first
	cur = conn.cursor()			
	log.info("Searching Game in DB")
	query = "select * from user_stats where id = %s;"
	cur.execute(query, [uid])
	#dbdata = cur.fetchone()
	if cur.rowcount > 0:
		log.info('Updating user_stats')
		datajson = jsonpickle.encode(data)
		#query = "UPDATE games SET groupName = %s, data = %s WHERE id = %s RETURNING data;"
		query = "UPDATE user_stats SET data = %s WHERE id = %s;"
		cur.execute(query, (datajson, uid))
		#log.info(cur.fetchone()[0])
		conn.commit()		
	else:
		log.info('Saving user_stats in DB')
		datajson = jsonpickle.encode(data)
		query = "INSERT INTO user_stats(id, data) VALUES (%s, %s);"
		#query = "INSERT INTO games(id , groupName  , data) VALUES (%s, %s, %s) RETURNING data;"
		cur.execute(query, (uid, datajson))
		#log.info(cur.fetchone()[0])
		conn.commit()

def load_player_stats(uid):
	cur = conn.cursor()			
	log.info("Searching Game in DB")
	query = "SELECT * FROM user_stats WHERE id = %s;"
	cur.execute(query, [uid])
	dbdata = cur.fetchone()

	if cur.rowcount > 0:
		log.info("user_stats Found")
		jsdata = dbdata[1]
		log.info("jsdata = {}".format(jsdata))				
		stats = jsonpickle.decode(jsdata)
		return stats
	else:
		log.info("user_stats Not Found")
		return None

##
# game_endcode:
#   -2  fascists win by electing Hitler as chancellor
#   -1  fascists win with 6 fascist policies
#   0   not ended
#   1   liberals win with 5 liberal policies
#   2   liberals win by killing Hitler
#   99  game cancelled
#		
def end_game(bot, game, game_endcode):
	log.info('end_game called')
	cid = game.cid
	
	# Grabo detalles de la partida
	save_game_details(bot, game.print_roles(), game_endcode, game.board.state.liberal_track, game.board.state.fascist_track, game.board.num_players)
	
	#bot.send_message(cid, "Datos a guardar %s %s %s %s %s" % (game.print_roles(), str(game_endcode), str(game.board.state.liberal_track), str(game.board.state.fascist_track), str(game.board.num_players)))
		
	stats = get_stats(bot, cid)	
	if game_endcode == 99:
		if GamesController.games[cid].board is not None:
			bot.send_message(cid, "Oyun iptal edildi!\n\n%s" % game.print_roles())
		else:
			bot.send_message(cid, "Oyun Bozuldu!")
		set_stats("cancelgame", stats[5] + 1, bot, cid)
	else:
		if game_endcode == -2:
			bot.send_message(game.cid, "Oyun Bitti! Faşistler, Hitler’i başkan yaparak kazandılar!\n\n%s" % game.print_roles())
			set_stats("fascistwinhitler", stats[1] + 1, bot, cid)
		if game_endcode == -1:
			bot.send_message(game.cid, "Oyun Bitti! Faşistler, 6 adet faşist yasası koyarak kazandı!\n\n%s" % game.print_roles())
			set_stats("fascistwinpolicies", stats[2] + 1, bot, cid)
		if game_endcode == 1:
			bot.send_message(game.cid, "Oyun Bitti! Liberaller, 5 faşist yasası koyarak kazandı!\n\n%s" % game.print_roles())
			set_stats("liberalwinpolicies", stats[3] + 1, bot, cid)
		if game_endcode == 2:
			bot.send_message(game.cid, "Oyun Bitti! Liberaller, Hitler’i vurarak kazandı!\n\n%s" % game.print_roles())
			set_stats("liberalwinkillhitler", stats[4] + 1, bot, cid)
		showHiddenhistory(bot, game)
	del GamesController.games[cid]
	Commands.delete_game(cid)
	
def showHiddenhistory(bot, game):
	#game.pedrote = 3
	try:
		#Check if there is a current game
		history_text = "Gizli Geçmiş:\n\n" 
		for x in game.hiddenhistory:				
			history_text += x + "\n"
		bot.send_message(game.cid, history_text, ParseMode.MARKDOWN)
	except Exception as e:
		bot.send_message(game.cid, str(e))
		log.error("Unknown error: " + str(e)) 
        
def inform_players(bot, game, cid, player_number):
	log.info('inform_players called')
	bot.send_message(cid,
		"Hadi %d oyuncu ile başlayalım!\n%s\nÖzel sohbete bak ve gizli rolünü öğren!" % (
		player_number, print_player_info(player_number)))
	available_roles = list(playerSets[player_number]["roles"])  # copy not reference because we need it again later
	# Mezclo los roles asi si alguien elije Fascista o Hitler no le toca siempre Fascista
	random.shuffle(available_roles)
	# Creo una lista unica para poder repartir los roles a partir de las key de los player list
	player_ids = list(game.playerlist.keys())
	# Lo mezclo y lo uso para pasar por todos los jugadores
	random.shuffle(player_ids)
	
	for uid in player_ids:
		# Antes de buscar un rol en particular pregunto si el jugador queria ser algo en particular
		preferencia_jugador = game.playerlist[uid].preference_rol		
		# Si el jugador tiene una preferencia... defecto se pone "" y daria [''] como preferencias		
		preferencias = preferencia_jugador.split('_')
		# El primer rol que aparece de las preferencias del jugador, devuelve None si no hay
		indice_preferencia = next((i for i,v in enumerate(available_roles) if v in preferencias), -1)
		
		# Si el jugador tiene una preferencia se le asigna esta, como el orden es random no se sabe si se sabe si se
		# cumplirá esto ya que los roles pudieron haber sido tomados ya.		
		if indice_preferencia == -1:
			#print "No hay indices de la preferencia"
			random_index = random.randrange(len(available_roles))
		else:
			random_index = indice_preferencia
			
		#log.info(str(random_index))
		role = available_roles.pop(random_index)
		#log.info(str(role))
		party = get_membership(role)
		game.playerlist[uid].role = role
		game.playerlist[uid].party = party
		
		# I comment so tyhe player aren't discturbed in testing, uncomment when deploy to production
		if not game.is_debugging:
			bot.send_message(uid, "Senin gizli rolün: %s\nParti üyeliğin: %s" % (role, party))
		else:
			bot.send_message(ADMIN, "El jugador %s es %s y su afiliación política es: %s" % (game.playerlist[uid].name, role, party))


def print_player_info(player_number):
    if player_number == 5:
        return "Oyunda 3 Liberal, 1 Faşist ve 1 Hitler var. Hitler faşistini görebilecek."
    elif player_number == 6:
        return "Oyunda 4 Liberal, 1 Faşist ve 1 Hitler var. Hitler faşistini görebilecek."
    elif player_number == 7:
        return "Oyunda 4 Liberal, 2 Faşist ve 1 Hitler var. Hitler faşistlerini göremeyecek."
    elif player_number == 8:
        return "Oyunda 5 Liberal, 2 Faşist ve 1 Hitler var. Hitler faşistlerini göremeyecek."
    elif player_number == 9:
        return "Oyunda 5 Liberal, 3 Faşist ve 1 Hitler var. Hitler faşistlerini göremeyecek."
    elif player_number == 10:
        return "Oyunda 6 Liberal, 3 Faşist ve 1 Hitler var. Hitler faşistlerini göremeyecek."


def inform_fascists(bot, game, player_number):
	log.info('inform_fascists called')

	for uid in game.playerlist:
		role = game.playerlist[uid].role
		if role == "Fascista":
			fascists = game.get_fascists()
			if player_number > 6:
				fstring = ""
				for f in fascists:
					if f.uid != uid:
						fstring += f.name + ", "
				fstring = fstring[:-2]
				if not game.is_debugging:
					bot.send_message(uid, "Faşist arkadaşların: %s" % fstring)
			hitler = game.get_hitler()
			if not game.is_debugging:
				bot.send_message(uid, "Hitler: %s" % hitler.name) #Uncoomend on production
		elif role == "Hitler":
			if player_number <= 6:
				fascists = game.get_fascists()
				if not game.is_debugging:
					bot.send_message(uid, "Faşist arkadaşların: %s" % fascists[0].name)
		elif role == "Liberal":
			pass
		else:
			log.error("inform_fascists: can\'t handle the role %s" % role)


def get_membership(role):
    log.info('get_membership called')
    if role == "Fascista" or role == "Hitler":
        return "fascista"
    elif role == "Liberal":
        return "liberal"
    else:
        return None


def increment_player_counter(game):
    log.info('increment_player_counter called')
    if game.board.state.player_counter < len(game.player_sequence) - 1:
        game.board.state.player_counter += 1
    else:
        game.board.state.player_counter = 0


def shuffle_policy_pile(bot, game):
	log.info('shuffle_policy_pile called')
	if len(game.board.policies) < 3:
		game.history.append("*No habia cartas suficientes en el mazo de políticas asi que he mezclado el resto con el mazo de descarte!*")
		game.hiddenhistory.append("*No habia cartas suficientes en el mazo de políticas asi que he mezclado el resto con el mazo de descarte!*")
		game.board.discards += game.board.policies
		game.board.policies = random.sample(game.board.discards, len(game.board.discards))
		game.board.discards = []		
		bot.send_message(game.cid,
			"Yasa destesinde yeterli kart kalmadı, ben de kalan kartları çekme destesiyle karıştırdım.!")

def getGamesByTipo(opcion):
	games = None
	cursor = conn.cursor()			
	log.info("Executing in DB")
	if opcion != "Todos":
		query = "select * from games g where g.tipojuego = '{0}'".format(opcion)
	else:
		query = "select * from games g"
	
	cursor.execute(query)
	if cursor.rowcount > 0:
		# Si encuentro juegos los busco a todos y los cargo en memoria
		for table in cursor.fetchall():
			if table[0] not in GamesController.games.keys():
				Commands.get_game(table[0])
		# En el futuro hacer que pueda hacer anuncios globales a todos los juegos ?
		games_restriction = [opcion]
		#bot.send_message(uid, "Obtuvo esta cantidad de juegos: {0}".format(len(GamesController.games)))
		# Luego aplico
		if opcion != "Todos":
			games = {key:val for key, val in GamesController.games.items() if val.tipo in games_restriction}
		else:
			games = GamesController.games		
	return games

def error_callback(update, context):
    logger.warning('Update "%s" caused error "%s"', update, context.error)

def change_groupname(bot, update):
	cid = update.message.chat.id
	groupname = update.message.chat.title
	game = Commands.get_game(cid)
	game.groupName = groupname
	bot.send_message(ADMIN, text="El group en {cid} ha cambiado de nombre a {groupname}".format(groupname=groupname, cid=cid))

def get_TOKEN():	
	cur = conn.cursor()
	query = "select * from config;"
	cur.execute(query)
	dbdata = cur.fetchone()
	token = dbdata[1]
	return token
	
def main():
	GamesController.init() #Call only once

	#Init DB Create tables if they don't exist   
	log.info('Init DB')
	conn.autocommit = True
	cur = conn.cursor()
	cur.execute(open("DBCreate.sql", "r").read())
	log.info('DB Created/Updated')
	conn.autocommit = False
	'''
	log.info('Insertando')
	query = "INSERT INTO users(facebook_id, name , access_token , created) values ('2','3','4',1) RETURNING id;"
	log.info('Por ejecutar')
	cur.execute(query)       
	user_id = cur.fetchone()[0]        
	log.info(user_id)


	query = "SELECT ...."
	cur.execute(query)
	'''

	# polling
	'''
	updater = Updater(get_TOKEN())
	'''
	# Pruebas de HOOKS
	token = os.environ.get('bot_token', None)
	updater = Updater(token, use_context=True)
	PORT = int(os.environ.get('PORT', '8443'))
	updater.start_webhook(listen="0.0.0.0",
                      port=PORT,
                      url_path=token)
	updater.bot.set_webhook("https://shitlertr.herokuapp.com/{0}".format(token))
	
	# Get the dispatcher to register handlers
	dp = updater.dispatcher

	# on different commands - answer in Telegram
	dp.add_handler(CommandHandler("start", Commands.command_start))
	dp.add_handler(CommandHandler("help", Commands.command_help))
	dp.add_handler(CommandHandler("board", Commands.command_board))
	dp.add_handler(CommandHandler("rules", Commands.command_rules))
	dp.add_handler(CommandHandler("heil", Commands.command_ping))
	dp.add_handler(CommandHandler("symbols", Commands.command_symbols))
	dp.add_handler(CommandHandler("stats", Commands.command_stats))
	dp.add_handler(CommandHandler("newgame", Commands.command_newgame))
	dp.add_handler(CommandHandler("startgame", Commands.command_startgame))
	dp.add_handler(CommandHandler("cancelgame", Commands.command_cancelgame))
	dp.add_handler(CommandHandler("join", Commands.command_join))
	dp.add_handler(CommandHandler("history", Commands.command_showhistory))
	dp.add_handler(CommandHandler("votes", Commands.command_votes))
	dp.add_handler(CommandHandler("calltovote", Commands.command_calltovote))	
	dp.add_handler(CommandHandler("claim", Commands.command_claim))
	dp.add_handler(CommandHandler("reload", Commands.command_reloadgame))
	dp.add_handler(CommandHandler("debug", Commands.command_toggle_debugging))
	dp.add_handler(CommandHandler("anarchy", Commands.command_anarquia))
	dp.add_handler(CommandHandler("prueba", Commands.command_prueba))
	dp.add_handler(CommandHandler("claimoculto", Commands.command_claim_oculto))
	dp.add_handler(CommandHandler("info", Commands.command_info))
	dp.add_handler(CallbackQueryHandler(pattern=r"(-?[0-9]*)\*chooseGameInfo\*(.*)\*(-?[0-9]*)", callback=Commands.callback_info))
	dp.add_handler(CommandHandler("jugadores", Commands.command_jugadores))

	#Testing commands
	dp.add_handler(CommandHandler("ja", Commands.command_ja))
	dp.add_handler(CommandHandler("nein", Commands.command_nein))

	dp.add_handler(CallbackQueryHandler(pattern="(-[0-9]*)_chan_(.*)", callback=nominate_chosen_chancellor))
	dp.add_handler(CallbackQueryHandler(pattern="(-[0-9]*)_insp_(.*)", callback=choose_inspect))
	dp.add_handler(CallbackQueryHandler(pattern="(-[0-9]*)_choo_(.*)", callback=choose_choose))
	dp.add_handler(CallbackQueryHandler(pattern="(-[0-9]*)_kill_(.*)", callback=choose_kill))
	dp.add_handler(CallbackQueryHandler(pattern="(-[0-9]*)_(yesveto|noveto)", callback=choose_veto))
	dp.add_handler(CallbackQueryHandler(pattern="(-[0-9]*)_(liberal|fascista|veto)", callback=choose_policy))
	dp.add_handler(CallbackQueryHandler(pattern="(-[0-9]*)_(Ja|Nein)", callback=handle_voting))
	dp.add_handler(CallbackQueryHandler(pattern="(-[0-9]*)_(SiAna|NoAna)", callback=handle_voting_anarquia))
	
	dp.add_handler(CommandHandler("comando", Commands.command_newgame_sql_command))
	
	# Comandos para elegir rol al unirse a la partida
	dp.add_handler(CommandHandler("role", Commands.command_choose_posible_role))
	dp.add_handler(CallbackQueryHandler(pattern=r"(-[0-9]*)\*chooserole\*(.*)\*([0-9]*)", callback=Commands.callback_choose_posible_role))

	dp.add_handler(CommandHandler("showstats", Commands.command_show_stats))
	dp.add_handler(CommandHandler("changestats", Commands.command_change_stats))

	dp.add_handler(MessageHandler(Filters.status_update.new_chat_title, change_groupname))
	
	# log all errors
	dp.add_error_handler(error_callback)

	# pruebas de hooks
	updater.idle()
	
	'''
	# Start the Bot
	updater.start_polling()
	# Run the bot until the you presses Ctrl-C or the process receives SIGINT,
	# SIGTERM or SIGABRT. This should be used most of the time, since
	# start_polling() is non-blocking and will stop the bot gracefully.
	updater.idle()
	'''


if __name__ == '__main__':
    main()
