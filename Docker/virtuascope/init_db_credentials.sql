CREATE USER 'ethoscope'@'%' IDENTIFIED BY 'ethoscope';
GRANT ALL PRIVILEGES ON *.* TO 'ethoscope'@'%' WITH GRANT OPTION;
FLUSH PRIVILEGES;
CREATE USER 'node'@'%' IDENTIFIED BY 'ethoscope';
GRANT ALL PRIVILEGES ON *.* TO 'node'@'%' WITH GRANT OPTION;
FLUSH PRIVILEGES;