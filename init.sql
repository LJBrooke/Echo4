create table element_list (
	id INTEGER PRIMARY KEY,
	primary_element TEXT,
	secondary_element TEXT,
	underbarrel BOOLEAN
);

CREATE TABLE unique_shields (
    id INTEGER,
    manufacturer TEXT,
	unique_perk TEXT,
    shield_name TEXT
);

CREATE TABLE unique_repkits (
    id INTEGER,
    manufacturer TEXT,
	unique_perk TEXT,
    repkit_name TEXT,
    repkit_effect TEXT
);

CREATE TABLE part_list (
    manufacturer TEXT,
    weapon_type TEXT,
    id INTEGER,
    part_type TEXT,
    part_string TEXT,
    model_name TEXT,
    stats TEXT,
    effects TEXT,
    requirements TEXT
);

CREATE TABLE type_and_manufacturer (
    id INTEGER PRIMARY KEY,
    manufacturer TEXT,
    item_type TEXT
);

CREATE TABLE shield_parts (
    id INTEGER,
    name TEXT,
    perk_type TEXT,
    shield_type TEXT,
    slot INTEGER
);

CREATE TABLE gadget_parts (
    id INTEGER,
    name TEXT,
    perk_type TEXT,
    description TEXT
);

CREATE TABLE repkit_parts (
    id INTEGER,
    name TEXT,
    perk_type TEXT,
    description TEXT
);

CREATE TABLE IF NOT EXISTS command_metrics (
    id SERIAL PRIMARY KEY,
    timestamp TIMESTAMPTZ DEFAULT NOW(),
    command_name VARCHAR(255) NOT NULL,
    response_time_ms FLOAT,
    user_type VARCHAR(50),
    guild_context VARCHAR(100),
    command_options TEXT
);

CREATE TABLE IF NOT EXISTS command_errors (
    id SERIAL PRIMARY KEY,
    timestamp TIMESTAMPTZ DEFAULT NOW(),
    command_name VARCHAR(255) NOT NULL,
    error_type VARCHAR(255),
    error_message TEXT,
    user_type VARCHAR(50),
    guild_context VARCHAR(100)
);

CREATE TABLE IF NOT EXISTS bot_health_stats (
    id SERIAL PRIMARY KEY,
    timestamp TIMESTAMPTZ DEFAULT NOW(),
    gateway_latency_ms FLOAT,
    guild_count INT
);

CREATE TABLE item_edit_history (
    id SERIAL PRIMARY KEY,
    session_id VARCHAR(255) NOT NULL,
    user_id BIGINT NOT NULL,
    "timestamp" TIMESTAMPTZ DEFAULT (now() at time zone 'utc'),
    edit_type VARCHAR(10) NOT NULL,
    item_name TEXT,
    item_type VARCHAR(100),
    manufacturer VARCHAR(100),
    serial TEXT,
    component_string TEXT,
    parts_json JSONB
);

CREATE TABLE characters (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) UNIQUE NOT NULL,
    class_name VARCHAR(100)
);
CREATE TABLE skill_trees (
    id SERIAL PRIMARY KEY,
    character_id INTEGER REFERENCES characters(id) ON DELETE CASCADE,
    name VARCHAR(100) NOT NULL
);
CREATE TABLE entities (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    source_category VARCHAR(100) NOT NULL,
    character_id INTEGER REFERENCES characters(id) ON DELETE SET NULL,
    tree_id INTEGER REFERENCES skill_trees(id) ON DELETE SET NULL,
    attributes JSONB
);

CREATE TABLE lootlemon_urls (
    game        VARCHAR(10) NOT NULL,    
    item_type   VARCHAR(50) NOT NULL,   
    url_stub    VARCHAR(255) PRIMARY KEY 
);

CREATE TABLE IF NOT EXISTS weapon_parts (
    part_number INTEGER PRIMARY KEY,
    part_name TEXT NOT NULL,
    part_type TEXT,
    stats JSONB NOT NULL
);

CREATE TABLE time_trials (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    submit_date TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    activity VARCHAR(64) NOT NULL,
    vault_hunter VARCHAR(32) NOT NULL,
    run_time INTERVAL NOT NULL,
    uvh_level INT,
    true_mode BOOLEAN DEFAULT FALSE,
    url VARCHAR(256),
    runner VARCHAR(64) NOT NULL,
    notes TEXT,
    action_skill VARCHAR(32),
    mark_as_deleted BOOLEAN DEFAULT FALSE,
    tags JSONB DEFAULT '[]'::jsonb,
    CONSTRAINT positive_time CHECK (run_time > INTERVAL '0 seconds')
);

CREATE TABLE IF NOT EXISTS time_trials_tag_definitions (
    tag_name TEXT PRIMARY KEY,
    description TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_leaderboard ON time_trials (activity, run_time ASC);

CREATE INDEX idx_time_trials_tags ON time_trials USING GIN (tags);

CREATE INDEX idx_runner_history ON time_trials (runner, activity);

CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE EXTENSION IF NOT EXISTS timescaledb;

CREATE INDEX idx_entities_name_trgm ON entities USING GIN (name gin_trgm_ops);

CREATE TABLE IF NOT EXISTS endgame_builds (
    id SERIAL PRIMARY KEY,
    vault_hunter TEXT NOT NULL,
    name TEXT NOT NULL,
    author TEXT NOT NULL,
    tree TEXT,
    class_mods TEXT[],
    description TEXT,
    moba_url TEXT,
    youtube_url TEXT,
    highlight_url TEXT
);

insert into element_list 
(id, primary_element, secondary_element, underbarrel)
values 
(1, 'Kinetic', Null, FALSE),
(2, 'Kinetic', Null, FALSE),
(3, 'Kinetic', Null, FALSE),
(4, 'Kinetic', Null, FALSE),
(5, 'Shock', 'Radiation', FALSE),
(6, 'Shock', 'Fire', FALSE),
(7, 'Shock', 'Cryo', FALSE),
(8, 'Shock', 'Corrosive', FALSE),
(9, 'Radiation', 'Shock', FALSE),
(10, 'Corrosive', Null, FALSE),
(11, 'Cryo', Null, FALSE),
(12, 'Fire', Null, FALSE),
(13, 'Radiation', Null, FALSE),
(14, 'Shock', Null, FALSE),
(15, 'Radiation', 'Fire', FALSE),
(16, 'Radiation', 'Cryo', FALSE),
(17, 'Radiation', 'Corrosive', FALSE),
(18, 'Fire', 'Radiation', FALSE),
(19, 'Fire', 'Cryo', FALSE),
(20, 'Fire', 'Corrosive', FALSE),
(21, 'Cryo', 'Shock', FALSE),
(22, 'Cryo', 'Radiation', FALSE),
(23, 'Cryo', 'Fire', FALSE),
(24, 'Cryo', 'Corrosive', FALSE),
(25, 'Corrosive', 'Shock', FALSE),
(26, 'Corrosive', 'Radiation', FALSE),
(27, 'Corrosive', 'Fire', FALSE),
(28, 'Corrosive', 'Cryo', FALSE),
(29, 'Shock', 'Radiation', TRUE),
(30, 'Fire', 'Radiation', TRUE),
(31, 'Cryo', 'Radiation', TRUE),
(32, 'Corrosive', 'Radiation', TRUE),
(33, 'Radiation', 'Corrosive', TRUE),
(34, 'Shock', 'Corrosive', TRUE),
(35, 'Fire', 'Corrosive', TRUE),
(36, 'Cryo', 'Corrosive', TRUE),
(37, 'Radiation', 'Cryo', TRUE),
(38, 'Shock', 'Cryo', TRUE),
(39, 'Fire', 'Cryo', TRUE),
(40, 'Corrosive', 'Cryo', TRUE),
(41, 'Radiation', 'Fire', TRUE),
(42, 'Cryo', 'Fire', TRUE),
(43, 'Shock', 'Fire', TRUE),
(44, 'Corrosive', 'Fire', TRUE),
(45, 'Radiation', 'Shock', TRUE),
(46, 'Cryo', 'Shock', TRUE),
(47, 'Corrosive', 'Shock', TRUE),
(48, 'Fire', 'Shock', FALSE),
(49, 'Fire', 'Shock', TRUE),
(50, 'Kinetic', Null, FALSE);



-- part list inserts are handled by the bot at initiation and on an adhoc basis.;

insert into type_and_manufacturer 
(id, manufacturer, item_type)
values 
(2, 'daedalus', 'pistol'),
(3, 'jakobs', 'pistol'),
(4, 'order', 'pistol'),
(5, 'tediore', 'pistol'),
(6, 'torgue', 'pistol'),
(7, 'ripper', 'shotgun'),
(8, 'daedalus', 'shotgun'),
(9, 'jakobs', 'shotgun'),
(10, 'maliwan', 'shotgun'),
(11, 'tediore', 'shotgun'),
(12, 'torgue', 'shotgun'),
(13, 'daedalus', 'assault_rifle'),
(14, 'tediore', 'assault_rifle'),
(15, 'order', 'assault_riffle'),
(16, 'vladof', 'sniper'),
(17, 'torgue', 'assault_rifle'),
(18, 'vladof', 'assault_rifle'),
(19, 'ripper', 'smg'),
(20, 'daedalus', 'smg'),
(21, 'maliwan', 'smg'),
(22, 'vladof', 'smg'),
(23, 'ripper', 'sniper'),
(24, 'jakobs', 'sniper'),
(25, 'maliwan', 'sniper'),
(26, 'order', 'sniper'),
(27, 'jakobs', 'assault_rifle'),
(254, 'siren', 'class_mod'),
(255, 'forgeknight', 'class_mod'),
(256, 'exo_soldier', 'class_mod'),
(259, 'gravitar', 'class_mod'),
(261, 'torgue', 'repair_kit'),
(263, 'maliwan', 'gadget'),
(264, 'hyperion', 'enhancement'),
(265, 'jakobs', 'repair_kit'),
(266, 'maliwan', 'repair_kit'),
(267, 'jakobs', 'gadget'),
(268, 'jakobs', 'enhancement'),
(269, 'vladof', 'repair_kit'),
(270, 'daedalus', 'gadget'),
(271, 'maliwan', 'enhancement'),
(272, 'order', 'gadget'),
(273, 'torgue', 'heavy'),
(274, 'ripper', 'repair_kit'),
(275, 'ripper', 'heavy'),
(277, 'daedalus', 'repair_kit'),
(278, 'ripper', 'gadget'),
(279, 'maliwan', 'shield'),
(281, 'order', 'enhancement'),
(282, 'vladof', 'heavy'),
(283, 'vladof', 'shield'),
(284, 'atlas', 'enhancement'),
(285, 'order', 'repair_kit'),
(286, 'cov', 'enhancement'),
(287, 'tediore', 'shield'),
(289, 'maliwan', 'heavy'),
(290, 'tediore', 'repair_kit'),
(291, 'vladof', 'gadget'),
(292, 'tediore', 'enhancement'),
(293, 'order', 'shield'),
(296, 'ripper', 'enhancement'),
(298, 'torgue', 'gadget'),
(299, 'daedalus', 'enhancement'),
(300, 'ripper', 'shield'),
(303, 'torgue', 'enhancement'),
(306, 'jakobs', 'shield'),
(310, 'vladof', 'enhancement'),
(311, 'tediore', 'gadget'),
(312, 'daedalus', 'shield'),
(321, 'torgue', 'shield');



insert into shield_parts 
(id, name, perk_type, shield_type, slot)
values 
(1, 'God Killer', 'Firmware', 'General', null),
(2, 'Reel Big Fist', 'Firmware', 'General', null),
(3, 'Lifeblood', 'Firmware', 'General', null),
(4, 'Airstrike', 'Firmware', 'General', null),
(5, 'High Caliber', 'Firmware', 'General', null),
(6, 'Gadget Ahoy', 'Firmware', 'General', null),
(7, 'Baker', 'Firmware', 'General', null),
(8, 'Oscar Mike', 'Firmware', 'General', null),
(9, 'Rubberband Man', 'Firmware', 'General', null),
(10, 'Deadeye', 'Firmware', 'General', null),
(11, 'Action Fist', 'Firmware', 'General', null),
(12, 'GooJFC', 'Firmware', 'General', null),
(13, 'Atlas E.X.', 'Firmware', 'General', null),
(14, 'Atlas Infinum', 'Firmware', 'General', null),
(15, 'Trickshot', 'Firmware', 'General', null),
(16, 'Jacked', 'Firmware', 'General', null),
(17, 'Get Throwin', 'Firmware', 'General', null),
(18, 'Heating Up', 'Firmware', 'General', null),
(19, 'Bullets to Spare', 'Firmware', 'General', null),
(20, 'Daed-dy O', 'Firmware', 'General', null),
(21, 'None', '', 'General', null),
(22, 'Corrosive', 'Elemental Resistance', 'General', null),
(23, 'Cryo', 'Elemental Resistance', 'General', null),
(24, 'Fire', 'Elemental Resistance', 'General', null),
(25, 'Rad', 'Elemental Resistance', 'General', null),
(26, 'Shock', 'Elemental Resistance', 'General', null),
(27, 'Utility 20%/10%', 'Perk', 'General', 1),
(28, 'Utility 28%/15%', 'Perk', 'General', 2),
(29, 'Turtle 40%/10%', 'Perk', 'General', 1),
(30, 'Turtle 65%/15%', 'Perk', 'General', 2),
(31, 'Sturdy 5%/20%', 'Perk', 'General', 1),
(32, 'Sturdy 8%/28%', 'Perk', 'General', 2),
(33, 'Spike Thorns effect damage', 'Perk', 'General', 1),
(34, 'Spike Thorns effect damage x2', 'Perk', 'General', 2),
(35, 'Resistance 17%', 'Perk', 'General', 1),
(36, 'Resistance 22%', 'Perk', 'General', 2),
(37, 'Reflect 15%', 'Perk', 'General', 1),
(38, 'Reflect 30%', 'Perk', 'General', 2),
(39, 'Power Booster 20%/10%', 'Perk', 'General', 1),
(40, 'Power Booster 30%/20%', 'Perk', 'General', 2),
(41, 'Pinpoint 20%/20%/25%', 'Perk', 'General', 1),
(42, 'Pinpoint 28%/28%/35%', 'Perk', 'General', 2),
(43, 'Overshield 10%', 'Perk', 'General', 1),
(44, 'Overshield 15%', 'Perk', 'General', 2),
(45, 'Mag Booster 10%', 'Perk', 'General', 1),
(46, 'Mag Booster 15%', 'Perk', 'General', 2),
(47, 'Health Booster 20%/15%', 'Perk', 'General', 1),
(48, 'Health Booster 30%/25%', 'Perk', 'General', 2),
(49, 'Healthy 10%', 'Perk', 'General', 1),
(50, 'Healthy 25%', 'Perk', 'General', 2),
(51, 'Evasive 5%/10%', 'Perk', 'General', 1),
(52, 'Evasive 8%/15%', 'Perk', 'General', 2),
(53, 'Capacity 25%', 'Perk', 'General', 1),
(54, 'Capacity 50%', 'Perk', 'General', 2),
(55, 'Adaptive 8%/20%', 'Perk', 'General', 1),
(56, 'Adaptive 16%/40%', 'Perk', 'General', 2),
(57, 'Absorb 15%', 'Perk', 'General', 1),
(58, 'Absorb 30%', 'Perk', 'General', 2),
(59, 'Nothing', '', 'General', null),
(60, 'Nothing', '', 'General', null),
(61, 'Nothing', '', 'General', null),
(62, 'Nothing', '', 'General', null),
(63, 'Nothing', '', 'General', null),
(64, 'Risky Boots', 'Firmware', 'General', null),
(1, 'Vagabond 28%', 'Perk', 'Energy', 2),
(2, 'Shield Booster 10%/13%', 'Perk', 'Energy', 1),
(3, 'Shield Booster 15%/18%', 'Perk', 'Energy', 2),
(4, 'Berserker 20%', 'Perk', 'Energy', 1),
(5, 'Berserker 28%', 'Perk', 'Energy', 2),
(6, 'Siphon 5%', 'Perk', 'Energy', 1),
(7, 'Siphon 10%', 'Perk', 'Energy', 2),
(8, 'Trigger Happy 20%/20%', 'Perk', 'Energy', 1),
(9, 'Trigger Happy 28%/28%', 'Perk', 'Energy', 2),
(10, 'Nova  ', 'Perk', 'Energy', 1),
(11, 'Nova', 'Perk', 'Energy', 2),
(12, 'Fleeting 20%', 'Perk', 'Energy', 1),
(13, 'Fleeting 28%', 'Perk', 'Energy', 2),
(14, 'Brimming 149', 'Perk', 'Energy', 1),
(15, 'Brimming 260', 'Perk', 'Energy', 2),
(16, 'Amp 20%/50%', 'Perk', 'Energy', 1),
(17, 'Amp 28%/100%', 'Perk', 'Energy', 2),
(18, 'Recharge Rate 20%', 'Perk', 'Energy', 1),
(19, 'Recharge Rate 30%', 'Perk', 'Energy', 2),
(20, 'Recharge delay -10%', 'Perk', 'Energy', 1),
(21, 'Recharge Delay -20%', 'Perk', 'Energy', 2),
(22, 'Nothing', '', 'Energy', null),
(23, 'Nothing', '', 'Energy', null),
(24, 'Nothing', '', 'Energy', null),
(25, 'Nothing', '', 'Energy', null),
(26, 'Nothing', '', 'Energy', null),
(27, 'Vagabond 20%', 'Perk', 'Energy', 1),
(28, 'Unknown', '', 'Energy', null),
(29, 'Unknown', '', 'Energy', null),
(30, 'Unknown', '', 'Energy', null),
(1, 'Scavenger 20%', 'Perk', 'Armour', 2),
(2, 'Reinforced Grants overshield', 'Perk', 'Armour', 1),
(3, 'Reinforced Grants more overshield', 'Perk', 'Armour', 2),
(4, 'Positive Reinforcement 15%', 'Perk', 'Armour', 1),
(5, 'Positive Reinforcement 25%', 'Perk', 'Armour', 2),
(6, 'Mini Nova nova damage', 'Perk', 'Armour', 1),
(7, 'Mini Nova more nova damage', 'Perk', 'Armour', 2),
(8, 'Missile Swarm 2 missiles for 744', 'Perk', 'Armour', 1),
(9, 'Missile Swarm 3 missiles for 1487', 'Perk', 'Armour', 2),
(10, 'Knockback 30%', 'Perk', 'Armour', 1),
(11, 'Knockback 40%', 'Perk', 'Armour', 2),
(12, 'Heavy Plating 20%', 'Perk', 'Armour', 1),
(13, 'Heavy Plating 35%', 'Perk', 'Armour', 2),
(14, 'Spunky 10%', 'Perk', 'Armour', 1),
(15, 'Spunky 20%', 'Perk', 'Armour', 2),
(16, 'Bladed 13%', 'Perk', 'Armour', 1),
(17, 'Bladed 20%', 'Perk', 'Armour', 2),
(18, 'Armor Strength 10%', 'Perk', 'Armour', 1),
(19, 'Armor Strength 20%', 'Perk', 'Armour', 2),
(20, 'Armor Segment +1', 'Perk', 'Armour', 1),
(21, 'Armor Segment +1', 'Perk', 'Armour', 2),
(22, 'Flanking 10%', 'Perk', 'Armour', 1),
(23, 'Flanking 18%', 'Perk', 'Armour', 2),
(24, 'Boxer 15%', 'Perk', 'Armour', 1),
(25, 'Boxer 25%', 'Perk', 'Armour', 2),
(26, 'White Item Card', 'Slot 1 lookup', 'Armour', null),
(27, 'Green Item Card', 'Slot 1 lookup', 'Armour', null),
(28, 'Blue Item Card', 'Slot 1 lookup', 'Armour', null),
(29, 'Purple Item Card', 'Slot 1 lookup', 'Armour', null),
(30, 'Leg Item Card', 'Slot 1 lookup', 'Armour', null),
(31, 'Scavenger 10%', 'Perk', 'Armour', 1);

insert into unique_shields 
(id, manufacturer, unique_perk, shield_name)
values 
(1, 'Maliwan', 'Vintage', 'Extra Medium'),
(8, 'Maliwan', 'Phyosis', 'Pandoran Memento'),
(6, 'Vladof', 'Refreshments', 'Hoarder'),
(8, 'Vladof', 'Bareknuckle', 'Heavyweight'),
(6, 'Tediore', 'Shield Boi', 'Principal'),
(9, 'Tediore', 'Bininu', 'Timekeeper''s New Shield'),
(1, 'Order', 'Glass', 'Cindershelly'),
(2, 'Order', 'Direct Current', 'Protean Cell'),
(6, 'Ripper', 'Short Circuit', 'Sparky Shield'),
(8, 'Ripper', 'Overshield Eater', 'Watts 4 Dinner'),
(7, 'Jakobs', 'Vintage', 'Oak-Aged Cask'),
(8, 'Jakobs', 'Shellot Shell', 'Onion'),
(6, 'Daedalus', 'Wings of Grace', 'Guardian Angel'),
(8, 'Daedalus', 'Power Play', 'Super Soldier'),
(6, 'Torgue', 'Bundled', 'Firewerks'),
(9, 'Torgue', 'Sisyphusian', 'Compleation');

insert into unique_repkits 
(id, manufacturer, unique_perk, repkit_name, repkit_effect)
values 
(1, 'Order', 'Heart Pump', 'Triple Bypass', 'This repkit has 3 charges and has a 30% chance to replenish a charge on kill'),
(6, 'Torgue', 'Chrome', 'War Paint', 'On use grants 30% fire rate and 30% movement speed for x seconds and reduced repkit cooldown time by 2 seconds every time damage is taken.'),
(1, 'Ripper', 'Time Dialation', 'AF1000', 'The repkits duration is increased by 100% and its cooldown duration is decreased by -50%'),
(1, 'Tediore', 'Blood Siphon', 'Kill Spring', 'On kill, converts 100% of any excess damage into healing orbs that seek out nearby allies.'),
(1, 'Daedalus', 'Pulsometer', 'Pacemaker', 'Passively regenerates health over time, increasing in rate when your health is low'),
(6, 'Jakobs', 'Cardiac Shot', 'Defibrillator', 'When health goes below 20%, 50% chance to replenish repkit charge'),
(6, 'Maliwan', 'Immunity Shot', 'Blood Analyzer', 'On use grants immunity to the last elemental damage taken for x seconds'),
(6, 'Vladof', 'Blood Rush', 'Adrenaline Pump', 'Automatically restores health on second wind');

insert into repkit_parts 
(id, name, perk_type, description)
values 
(1,     'God Killer', 'Firmware', null),
(2,     'Reel Big Fist', 'Firmware', null),
(3,     'Lifeblood', 'Firmware', null),
(4,     'Airstrike', 'Firmware', null),
(5,     'High Caliber', 'Firmware', null),
(6,     'Gadget Ahoy', 'Firmware', null),
(7,     'Baker', 'Firmware', null),
(8,     'Oscar Mike', 'Firmware', null),
(9,     'Rubberband Man', 'Firmware', null),
(10,    'Deadeye', 'Firmware', null),
(11,    'Action Fist', 'Firmware', null),
(12,    'GooJFC', 'Firmware', null),
(13,    'Atlas E.X.', 'Firmware', null),
(14,    'Atlas Infinum', 'Firmware', null),
(15,    'Trickshot', 'Firmware', null),
(16,    'Jacked', 'Firmware', null),
(17,    'Get Throwin', 'Firmware', null),
(18,    'Heating Up', 'Firmware', null),
(19,    'Bullets to Spare', 'Firmware', null),
(20,    'Daed-dy O', 'Firmware', null),
(21,    'Nothing', null, null),
(22,    'Shock', 'Resistance', '+50% Shock Resistance for 10s'),
(23,    'Radiation', 'Resistance', '+50% Radiation Resistance for 10s'),
(24,    'Fire', 'Resistance', '+50% Fire Resistance for 10s'),
(25,    'Cryo', 'Resistance', '+50% Cryo Resistance for 10s'),
(26,    'Corrosive', 'Resistance', '+50% Corrosive Resistance for 10s'),
(27,    'Shock', 'Immunity', 'Shock Immunity for 3s'),
(28,    'Radiation', 'Immunity', 'Radiation Immunity for 3s'),
(29,    'Fire', 'Immunity', 'Fire Immunity for 3s'),
(30,    'Cryo', 'Immunity', 'Cryo Immunity for 3s'),
(31,    'Corrosive', 'Immunity', 'Corrosive Immunity for 3s'),
(32,    'Shock Splat', 'Splat', null),
(33,    'Radiation Splat', 'Splat', null),
(34,    'Cryo Splat', 'Splat', null),
(35,    'Corrosive Splat', 'Splat', null),
(36,    'Fire Splat', 'Splat', null),
(37,    'Corrosive Nova', 'Nova', null),
(38,    'Cryo Nova', 'Nova', null),
(39,    'Fire Nova', 'Nova', null),
(40,    'Radiation Nova', 'Nova', null),
(41,    'Shock Nova', 'Nova', null),
(42,    'Shock Immunity', 'Shock Immunity for 3s', null),
(43,    'Radiation Immunity', 'Radiation Immunity for 3s', null),
(44,    'Fire Immunity', 'Fire Immunity for 3s', null),
(45,    'Cryo Immunity', 'Cryo Immunity for 3s', null),
(46,    'Corrosive Immunity', 'Corrosive Immunity for 3s', null),
(47,    'Shock Resistance', '+50% Shock Resistance for 10s', null),
(48,    'Radiation Resistance', '+50% Radiation Resistance for 10s', null),
(49,    'Fire Resistance', '+50% Fire Resistance for 10s', null),
(50,    'Cryo Resistance', '+50% Cryo Resistance for 10s', null),
(51,    'Corrosive Resistance', '+50% Corrosive Resistance for 10s', null),
(52,    'Medic', 'Perk', 'Heals nearby allies for 50% of the healing amount'),
(53,    'Nothing', 'Perk', null),
(54,    'Overshield', 'Perk', 'Overshield of initial heal amount instead of healing'),
(55,    'Nothing', 'Perk', null),
(56,    'Health Burst', 'Perk', 'Additional burst of half initial value after 6s'),
(57,    'Power Cycle', 'Perk', 'Instantly start recharging Energy Shield'),
(58,    'Leech', 'Perk', '30% Lifesteel for 6s'),
(59,    'Tank', 'Perk', '-50% Damage Taken for 6s'),
(60,    'Everlasting', 'Perk', '+20% Capacity and Duration'),
(61,    'Enrage', 'Perk', '+30% Damage Dealth, +15% Damage Taken for 8s'),
(62,    'Accelerator', 'Perk', '+50% Action Skill Cooldown Rate for 8s'),
(63,    'Elemental Affinity', 'Perk', '+25% Elemental Damage for 8s'),
(64,    'Splash Damage', 'Perk', '+25% Splash Damage for 8s'),
(65,    'Reload Speed', 'Perk', '+25% Reload speed for 8s'),
(66,    'Lower healing, longer cooldown', 'Perk', null),
(67,    'Speed', 'Perk', '+40% Movement Speed for 6s'),
(68,    'Go Go Gadget', 'Perk', '+50% Ordnance Cooldown Rate for 8s'),
(69,    'Hard Hitter', 'Perk', '+40% Melee Damage for 8s'),
(70,    'Overdose', 'Perk', '+45% All Healing Recieved for 6s'),
(71,    'Fire Rate', 'Perk', '+15% Fire Rate for 8s'),
(72,    'Nothing', 'Perk', null),
(73,    'Amp', 'Perk', '+200% Damage for next shot'),
(74,    'Repkit Cooling', 'Perk', '-33% Repkit Cooldown Duration'),
(75,    'Medic', 'repeat', 'Heals nearby allies for 50% of the healing amount'),
(76,    'Nothing', 'repeat', 'different look'),
(77,    'Overshield', 'repeat', 'Overshield of initial heal amount instead of healing'),
(78,    'Nothing', 'repeat', 'different look'),
(79,    'Health Burst', 'repeat', 'Additional burst of half initial value after 6s'),
(80,    'Power Cycle', 'repeat', 'Instantly start recharging Energy Shield'),
(81,    'Leech', 'repeat', '30% Lifesteel for 6s'),
(82,    'Tank', 'repeat', '-50% Damage Taken for 6s'),
(83,    'Everlasting', 'repeat', '+20% Capacity and Duration'),
(84,    'Enrage', 'repeat', '+30% Damage Dealth, +15% Damage Taken for 8s'),
(85,    'Accelerator', 'repeat', '+50% Action Skill Cooldown Rate for 8s'),
(86,    'Elemental Affinity', 'repeat', '+25% Elemental Damage for 8s'),
(87,    'Splash Damage', 'repeat', '+25% Splash Damage for 8s'),
(88,    'Reload Speed', 'repeat', '+25% Reload speed for 8s'),
(89,    'Lower healing, longer cooldown', 'repeat', null),
(90,    'Speed', 'repeat', '+40% Movement Speed for 6s'),
(91,    'Go Go Gadget', 'repeat', '+50% Ordnance Cooldown Rate for 8s'),
(92,    'Hard Hitter', 'repeat', '+40% Melee Damage for 8s'),
(93,    'Overdose', 'repeat', '+45% All Healing Recieved for 6s'),
(94,    'Fire Rate', 'repeat', '+15% Fire Rate for 8s'),
(95,    'Nothing', 'repeat', 'different look'),
(96,    'Amp', 'repeat', '+200% Damage for next shot'),
(97,    'Repkit Cooling', 'repeat', '-33% Repkit Cooldown Duration'),
(98,    'Nothing', null, null),
(99,    'Nothing', null, null),
(100,   'Nothing', null, null),
(101,   'Nothing', null, null),
(102,   'Nothing', null, null),
(103,   'Mini', 'Perk', 'Lower healing amount and cooldown'),
(104,   'Standard', 'Perk', null),
(105,   'Large', 'Perk', 'More healing, longer cooldown'),
(106,   'Mega',	'Perk', 'Even more healing, even longer cooldown');

INSERT INTO entities (name, source_category, character_id, tree_id, attributes)
VALUES
  ('Accelerator', 'Enhancement', NULL, NULL,
    $$ {"effect": "Daedalus parts gain +1% Fire Rate/bullets fired , Max 50x, resets on Reload.", "manufacturer": "Daedalus"} $$::jsonb
  ),
  ('Backup Plan', 'Enhancement', NULL, NULL,
    $$ {"effect": "Guns with Daedalus parts slowly regenerate reserve Ammo while equipped.", "manufacturer": "Daedalus"} $$::jsonb
  ),
  ('Mixologist', 'Enhancement', NULL, NULL,
    $$ {"effect": "Guns with Maliwan parts deal +10% Bonus Damage from the inactive Mode's Element.", "manufacturer": "Maliwan", "damage_type": "Bonus Element"} $$::jsonb
  ),
  ('Primed Potency', 'Enhancement', NULL, NULL,
    $$ {"effect": "Guns with Maliwan parts have +100% Status Effect Chance on the first bullet after Reload.", "manufacturer": "Maliwan"} $$::jsonb
  ),
  ('Freeloader', 'Enhancement', NULL, NULL,
    $$ {"effect": "Guns with Ripper parts have a 30% Chance to instantly refill its Magazine when it's empty.", "manufacturer": "Ripper"} $$::jsonb
  ),
  ('Short Circuit', 'Enhancement', NULL, NULL,
    $$ {"effect": "After Reloading an empty Magazine, Guns with Ripper parts have a 30% Chance to increase the next Magazine's Fire Rate by +100%.", "manufacturer": "Ripper"} $$::jsonb
  ),
  ('Stabilizer', 'Enhancement', NULL, NULL,
    $$ {"effect": "Guns with Hyperion parts gain +40% Accuracy.", "manufacturer": "Hyperion"} $$::jsonb
  ),
  ('Bulwark', 'Enhancement', NULL, NULL,
    $$ {"effect": "Guns with Hyperion parts gain +100% Gun Shield Capacity.", "manufacturer": "Hyperion"} $$::jsonb
  ),
  ('Headringer', 'Enhancement', NULL, NULL,
    $$ {"effect": "Guns with Torgue parts gain +25% Damage, and +100% Damage Radius.", "manufacturer": "Torgue", "damage_type": "Enhancement"} $$::jsonb
  ),
  ('Boompuppy', 'Enhancement', NULL, NULL,
    $$ {"effect": "Guns with Torgue parts have a 50% Chance to call down a Missile Barrage on a nearby enemy.", "manufacturer": "Torgue"} $$::jsonb
  ),
  ('High Roller', 'Enhancement', NULL, NULL,
    $$ {"effect": "Guns with Ripper parts increase Gun Damage by 2% for each consecutive shot, for a Maximum 25 Stacks.", "manufacturer": "Ripper", "damage_type": "Enhancement"} $$::jsonb
  ),
  ('Leaper', 'Enhancement', NULL, NULL,
    $$ {"effect": "Guns with Jakobs parts gain 40% Chance to Ricochet non-Critical Hits.", "manufacturer": "Jakobs"} $$::jsonb
  ),
  ('Bounce Pass', 'Enhancement', NULL, NULL,
    $$ {"effect": "Guns with Jakobs parts increase the number of possible Ricochets by 1.", "manufacturer": "Jakobs", "damage_type": "Enhancement"} $$::jsonb
  ),
  ('Explosi-ception', 'Enhancement', NULL, NULL,
    $$ {"effect": "Guns with Torgue Sticky Magazines deal +50% of Gun Damage on impact.", "manufacturer": "Torgue"} $$::jsonb
  ),
  ('Stim Converter', 'Enhancement', NULL, NULL,
    $$ {"effect": "Guns with Hyperion parts regenerate up to 10% Health when the Gun Shield is hit.", "manufacturer": "Hyperion"} $$::jsonb
  ),
  ('Bottom Feeder', 'Enhancement', NULL, NULL,
    $$ {"effect": "Guns with Vladof parts reduce Underbarrel Cooldown Duration by 40%.", "manufacturer": "Vladof"} $$::jsonb
  ),
  ('Underdog', 'Enhancement', NULL, NULL,
    $$ {"effect": "Guns with Vladof-licensed parts gain +50% Underbarrel Damage.", "manufacturer": "Vladof", "damage_type": "Enhancement"} $$::jsonb
  ),
  ('Muzzle Break', 'Enhancement', NULL, NULL,
    $$ {"effect": "Guns with Order parts gain +50% Acc & Burst Fire Speed when firing Max Charge.", "manufacturer": "Order"} $$::jsonb
  ),
  ('Free Charger', 'Enhancement', NULL, NULL,
    $$ {"effect": "Guns with Order parts have a 30% Chance to make the next shot's Charge Time and Ammo cost 0 when firing from Maximum Charge.", "manufacturer": "Order"} $$::jsonb
  ),
  ('Hard Charger', 'Enhancement', NULL, NULL,
    $$ {"effect": "Guns with Ripper parts gain +25% dmg, but Charge Time is increased by 30%.", "manufacturer": "Ripper", "damage_type": "Enhancement"} $$::jsonb
  ),
  ('Power Shot', 'Enhancement', NULL, NULL,
    $$ {"effect": "Guns with Order parts gain 30% Damage when firing from Maximum Charge.", "manufacturer": "Order", "damage_type": "Enhancement"} $$::jsonb
  ),
  ('Digi-Divider', 'Enhancement', NULL, NULL,
    $$ {"effect": "Guns with Tediore parts have a 50% Chance to spawn another Projectile Reload.", "manufacturer": "Tediore"} $$::jsonb
  ),
  ('Extend-a-friend', 'Enhancement', NULL, NULL,
    $$ {"effect": "Guns with Tediore parts have a +50% longer Lifetime for Thrown Turrets.", "manufacturer": "Tediore"} $$::jsonb
  ),
  ('Synthesizer', 'Enhancement', NULL, NULL,
    $$ {"effect": "Guns with Maliwan parts have +25% Status Effect Damage.", "manufacturer": "Maliwan", "damage_type": "Soup"} $$::jsonb
  ),
  ('Transfuser', 'Enhancement', NULL, NULL,
    $$ {"effect": "On kill, Guns with Maliwan parts spread their active Status Effect to up to 3 nearby targets.", "manufacturer": "Maliwan"} $$::jsonb
  ),
  ('Air Burst', 'Enhancement', NULL, NULL,
    $$ {"effect": "Guns with Torgue parts fire Projectiles that explode on proximity.", "manufacturer": "Torgue"} $$::jsonb
  ),
  ('Stockpiler', 'Enhancement', NULL, NULL,
    $$ {"effect": "On Reload, Guns with Daedalus parts gain up to +25% Damage based on the amount of spare Ammo for currently-equipped Gun.", "manufacturer": "Daedalus", "damage_type": "Enhancement"} $$::jsonb
  ),
  ('Cold Open', 'Enhancement', NULL, NULL,
    $$ {"effect": "Guns with COV Magazines gain +20% Damage when below 50% heat.", "manufacturer": "COV", "damage_type": "Enhancement"} $$::jsonb
  ),
  ('Ventilator', 'Enhancement', NULL, NULL,
    $$ {"effect": "Guns with COV Magazines have a 25% Chance to cost 0 Heat when fired.", "manufacturer": "COV"} $$::jsonb
  ),
  ('Banger', 'Enhancement', NULL, NULL,
    $$ {"effect": "Guns with Tediore parts use +50% Maximum Loaded Ammo when calculating Thrown Damage.", "manufacturer": "Tediore"} $$::jsonb
  ),
  ('Sequencer', 'Enhancement', NULL, NULL,
    $$ {"effect": "Guns with Jakobs parts grant consecutive Critical Hits a stacking +5% Bonus Damage, for a Maximum 8 Stacks.", "manufacturer": "Jakobs", "damage_type": "Enhancement"} $$::jsonb
  ),
  ('Bullet Fabricator', 'Enhancement', NULL, NULL,
    $$ {"effect": "On kill, Daedalus parts have a 40% Chance to refill your Mags.", "manufacturer": "Daedalus"} $$::jsonb
  ),
  ('Bullet Hose', 'Enhancement', NULL, NULL,
    $$ {"effect": "Guns with Vladof parts have a 30% Chance to add an extra Projectile per shot.", "manufacturer": "Vladof"} $$::jsonb
  ),
  ('Box Magazine', 'Enhancement', NULL, NULL,
    $$ {"effect": "Guns with Vladof parts gain +20% Fire Rate and +20% Magazine Size.", "manufacturer": "Vladof"} $$::jsonb
  ),
  ('Ammo Generator', 'Enhancement', NULL, NULL,
    $$ {"effect": "Guns with Order parts slowly refill from reserve Ammo while held.", "manufacturer": "Order"} $$::jsonb
  ),
  ('Shock Guard', 'Enhancement', NULL, NULL,
    $$ {"effect": "Guns with Hyperion parts trigger a Shock Nova when deployed (this feature has an 8s Cooldown).", "manufacturer": "Hyperion"} $$::jsonb
  ),
  ('Recycler', 'Enhancement', NULL, NULL,
    $$ {"effect": "Guns with Tediore parts keep 50% of a Magazine's Ammo on Reload.", "manufacturer": "Tediore"} $$::jsonb
  ),
  ('Smelter', 'Enhancement', NULL, NULL,
    $$ {"effect": "Guns with COV Magazines have a +35% Fire Rate when over 50% Heat.", "manufacturer": "COV"} $$::jsonb
  ),
  ('Duct Tape', 'Enhancement', NULL, NULL,
    $$ {"effect": "Guns with COV Magazines have a 100% Chance to deal Critical Damage while Overheating.", "manufacturer": "COV"} $$::jsonb
  ),
  ('Piercer', 'Enhancement', NULL, NULL,
    $$ {"effect": "Guns with Jakobs parts have a 20% chance to grant a Critical Hit.", "manufacturer": "Jakobs"} $$::jsonb
  ),
  ('Sure Shot', 'Enhancement', NULL, NULL,
    $$ {"effect": "Projectiles from Guns with Atlas parts automatically attach a Tracker Dart every 25s.", "manufacturer": "Atlas"} $$::jsonb
  ),
  ('Trauma Bond', 'Enhancement', NULL, NULL,
    $$ {"effect": "Guns with Atlas parts gain +30% Damage while Target Lock is active.", "manufacturer": "Atlas", "damage_type": "Enhancement"} $$::jsonb
  ),
  ('Protractor', 'Enhancement', NULL, NULL,
    $$ {"effect": "Guns with Atlas parts have a +50% Chance to not consume Ammo while Target Lock is active.", "manufacturer": "Atlas"} $$::jsonb
  ),
  ('Tracker Antenna', 'Enhancement', NULL, NULL,
    $$ {"effect": "Guns with Atlas parts gain +40% Fire Rate while Target Lock is active.", "manufacturer": "Atlas"} $$::jsonb
  );