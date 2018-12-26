--DROP TABLE IF EXISTS users;
--DROP TABLE IF EXISTS games;

CREATE TABLE IF NOT EXISTS users (
    id bigint PRIMARY KEY,
    name text NOT NULL
);

CREATE TABLE IF NOT EXISTS games (
    id bigint PRIMARY KEY,
    groupName TEXT NOT NULL,
    data text NOT NULL
);

CREATE TABLE IF NOT EXISTS stats (
    id bigint PRIMARY KEY,
    fascistwinhitler INTEGER NOT NULL,
    fascistwinpolicies INTEGER NOT NULL,
    liberalwinpolicies INTEGER NOT NULL,
    liberalwinkillhitler INTEGER NOT NULL,
    cancelgame INTEGER NOT NULL
);

--DROP TABLE IF EXISTS stats_detail;

CREATE TABLE IF NOT EXISTS stats_detail (
    id SERIAL PRIMARY KEY,
    playerlist TEXT,
    game_endcode INTEGER NOT NULL,
    liberal_track INTEGER NOT NULL,
    fascist_track INTEGER NOT NULL,
    num_players INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS config (
     id bigint PRIMARY KEY,
     token TEXT NOT NULL
 );
 
 INSERT INTO config VALUES (1, '443814179:AAH9lpzfxGUC7XAKNh8uV5r9NCDx6lGBQJM');

--INSERT INTO stats VALUES (1, 0, 0, 0, 0, 0);
