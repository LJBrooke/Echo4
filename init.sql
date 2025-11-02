create table element_list (
	id INTEGER PRIMARY KEY,
	primary_element TEXT,
	secondary_element TEXT,
	underbarrel BOOLEAN
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

-- insert into part_list (id) values (1);