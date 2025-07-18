-- MariaDB dump 10.19-11.2.2-MariaDB, for Linux (armv7l)
--
-- Host: localhost    Database: ETHOSCOPE_285_db
-- ------------------------------------------------------
-- Server version	11.2.2-MariaDB-log

/*!40101 SET @OLD_CHARACTER_SET_CLIENT=@@CHARACTER_SET_CLIENT */;
/*!40101 SET @OLD_CHARACTER_SET_RESULTS=@@CHARACTER_SET_RESULTS */;
/*!40101 SET @OLD_COLLATION_CONNECTION=@@COLLATION_CONNECTION */;
/*!40101 SET NAMES utf8mb4 */;
/*!40103 SET @OLD_TIME_ZONE=@@TIME_ZONE */;
/*!40103 SET TIME_ZONE='+00:00' */;
/*!40014 SET @OLD_UNIQUE_CHECKS=@@UNIQUE_CHECKS, UNIQUE_CHECKS=0 */;
/*!40014 SET @OLD_FOREIGN_KEY_CHECKS=@@FOREIGN_KEY_CHECKS, FOREIGN_KEY_CHECKS=0 */;
/*!40101 SET @OLD_SQL_MODE=@@SQL_MODE, SQL_MODE='NO_AUTO_VALUE_ON_ZERO' */;
/*!40111 SET @OLD_SQL_NOTES=@@SQL_NOTES, SQL_NOTES=0 */;

--
-- Table structure for table `CSV_DAM_ACTIVITY`
--

DROP TABLE IF EXISTS `CSV_DAM_ACTIVITY`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `CSV_DAM_ACTIVITY` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `date` char(100) DEFAULT NULL,
  `time` char(100) DEFAULT NULL,
  `DUMMY_FIELD_0` smallint(6) DEFAULT NULL,
  `DUMMY_FIELD_1` smallint(6) DEFAULT NULL,
  `DUMMY_FIELD_2` smallint(6) DEFAULT NULL,
  `DUMMY_FIELD_3` smallint(6) DEFAULT NULL,
  `DUMMY_FIELD_4` smallint(6) DEFAULT NULL,
  `DUMMY_FIELD_5` smallint(6) DEFAULT NULL,
  `DUMMY_FIELD_6` smallint(6) DEFAULT NULL,
  `ROI_1` smallint(6) DEFAULT NULL,
  `ROI_2` smallint(6) DEFAULT NULL,
  `ROI_3` smallint(6) DEFAULT NULL,
  `ROI_4` smallint(6) DEFAULT NULL,
  `ROI_5` smallint(6) DEFAULT NULL,
  `ROI_6` smallint(6) DEFAULT NULL,
  `ROI_7` smallint(6) DEFAULT NULL,
  `ROI_8` smallint(6) DEFAULT NULL,
  `ROI_9` smallint(6) DEFAULT NULL,
  `ROI_10` smallint(6) DEFAULT NULL,
  `ROI_11` smallint(6) DEFAULT NULL,
  `ROI_12` smallint(6) DEFAULT NULL,
  `ROI_13` smallint(6) DEFAULT NULL,
  `ROI_14` smallint(6) DEFAULT NULL,
  `ROI_15` smallint(6) DEFAULT NULL,
  `ROI_16` smallint(6) DEFAULT NULL,
  `ROI_17` smallint(6) DEFAULT NULL,
  `ROI_18` smallint(6) DEFAULT NULL,
  `ROI_19` smallint(6) DEFAULT NULL,
  `ROI_20` smallint(6) DEFAULT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=14056 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci KEY_BLOCK_SIZE=16;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `IMG_SNAPSHOTS`
--

DROP TABLE IF EXISTS `IMG_SNAPSHOTS`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `IMG_SNAPSHOTS` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `t` int(11) DEFAULT NULL,
  `img` longblob DEFAULT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=2812 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci KEY_BLOCK_SIZE=16;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `METADATA`
--

DROP TABLE IF EXISTS `METADATA`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `METADATA` (
  `field` char(100) DEFAULT NULL,
  `value` varchar(3000) DEFAULT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci KEY_BLOCK_SIZE=16;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `ROI_1`
--

DROP TABLE IF EXISTS `ROI_1`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `ROI_1` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `t` int(11) DEFAULT NULL,
  `x` smallint(6) DEFAULT NULL,
  `y` smallint(6) DEFAULT NULL,
  `w` smallint(6) DEFAULT NULL,
  `h` smallint(6) DEFAULT NULL,
  `phi` smallint(6) DEFAULT NULL,
  `xy_dist_log10x1000` smallint(6) DEFAULT NULL,
  `is_inferred` tinyint(1) DEFAULT NULL,
  `has_interacted` smallint(6) DEFAULT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=1541026 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci KEY_BLOCK_SIZE=16;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `ROI_10`
--

DROP TABLE IF EXISTS `ROI_10`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `ROI_10` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `t` int(11) DEFAULT NULL,
  `x` smallint(6) DEFAULT NULL,
  `y` smallint(6) DEFAULT NULL,
  `w` smallint(6) DEFAULT NULL,
  `h` smallint(6) DEFAULT NULL,
  `phi` smallint(6) DEFAULT NULL,
  `xy_dist_log10x1000` smallint(6) DEFAULT NULL,
  `is_inferred` tinyint(1) DEFAULT NULL,
  `has_interacted` smallint(6) DEFAULT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=571091 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci KEY_BLOCK_SIZE=16;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `ROI_11`
--

DROP TABLE IF EXISTS `ROI_11`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `ROI_11` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `t` int(11) DEFAULT NULL,
  `x` smallint(6) DEFAULT NULL,
  `y` smallint(6) DEFAULT NULL,
  `w` smallint(6) DEFAULT NULL,
  `h` smallint(6) DEFAULT NULL,
  `phi` smallint(6) DEFAULT NULL,
  `xy_dist_log10x1000` smallint(6) DEFAULT NULL,
  `is_inferred` tinyint(1) DEFAULT NULL,
  `has_interacted` smallint(6) DEFAULT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=1556825 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci KEY_BLOCK_SIZE=16;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `ROI_12`
--

DROP TABLE IF EXISTS `ROI_12`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `ROI_12` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `t` int(11) DEFAULT NULL,
  `x` smallint(6) DEFAULT NULL,
  `y` smallint(6) DEFAULT NULL,
  `w` smallint(6) DEFAULT NULL,
  `h` smallint(6) DEFAULT NULL,
  `phi` smallint(6) DEFAULT NULL,
  `xy_dist_log10x1000` smallint(6) DEFAULT NULL,
  `is_inferred` tinyint(1) DEFAULT NULL,
  `has_interacted` smallint(6) DEFAULT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=1588332 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci KEY_BLOCK_SIZE=16;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `ROI_13`
--

DROP TABLE IF EXISTS `ROI_13`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `ROI_13` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `t` int(11) DEFAULT NULL,
  `x` smallint(6) DEFAULT NULL,
  `y` smallint(6) DEFAULT NULL,
  `w` smallint(6) DEFAULT NULL,
  `h` smallint(6) DEFAULT NULL,
  `phi` smallint(6) DEFAULT NULL,
  `xy_dist_log10x1000` smallint(6) DEFAULT NULL,
  `is_inferred` tinyint(1) DEFAULT NULL,
  `has_interacted` smallint(6) DEFAULT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=1588238 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci KEY_BLOCK_SIZE=16;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `ROI_14`
--

DROP TABLE IF EXISTS `ROI_14`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `ROI_14` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `t` int(11) DEFAULT NULL,
  `x` smallint(6) DEFAULT NULL,
  `y` smallint(6) DEFAULT NULL,
  `w` smallint(6) DEFAULT NULL,
  `h` smallint(6) DEFAULT NULL,
  `phi` smallint(6) DEFAULT NULL,
  `xy_dist_log10x1000` smallint(6) DEFAULT NULL,
  `is_inferred` tinyint(1) DEFAULT NULL,
  `has_interacted` smallint(6) DEFAULT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=1543214 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci KEY_BLOCK_SIZE=16;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `ROI_15`
--

DROP TABLE IF EXISTS `ROI_15`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `ROI_15` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `t` int(11) DEFAULT NULL,
  `x` smallint(6) DEFAULT NULL,
  `y` smallint(6) DEFAULT NULL,
  `w` smallint(6) DEFAULT NULL,
  `h` smallint(6) DEFAULT NULL,
  `phi` smallint(6) DEFAULT NULL,
  `xy_dist_log10x1000` smallint(6) DEFAULT NULL,
  `is_inferred` tinyint(1) DEFAULT NULL,
  `has_interacted` smallint(6) DEFAULT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=1588294 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci KEY_BLOCK_SIZE=16;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `ROI_16`
--

DROP TABLE IF EXISTS `ROI_16`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `ROI_16` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `t` int(11) DEFAULT NULL,
  `x` smallint(6) DEFAULT NULL,
  `y` smallint(6) DEFAULT NULL,
  `w` smallint(6) DEFAULT NULL,
  `h` smallint(6) DEFAULT NULL,
  `phi` smallint(6) DEFAULT NULL,
  `xy_dist_log10x1000` smallint(6) DEFAULT NULL,
  `is_inferred` tinyint(1) DEFAULT NULL,
  `has_interacted` smallint(6) DEFAULT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=1504012 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci KEY_BLOCK_SIZE=16;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `ROI_17`
--

DROP TABLE IF EXISTS `ROI_17`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `ROI_17` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `t` int(11) DEFAULT NULL,
  `x` smallint(6) DEFAULT NULL,
  `y` smallint(6) DEFAULT NULL,
  `w` smallint(6) DEFAULT NULL,
  `h` smallint(6) DEFAULT NULL,
  `phi` smallint(6) DEFAULT NULL,
  `xy_dist_log10x1000` smallint(6) DEFAULT NULL,
  `is_inferred` tinyint(1) DEFAULT NULL,
  `has_interacted` smallint(6) DEFAULT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=1588405 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci KEY_BLOCK_SIZE=16;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `ROI_18`
--

DROP TABLE IF EXISTS `ROI_18`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `ROI_18` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `t` int(11) DEFAULT NULL,
  `x` smallint(6) DEFAULT NULL,
  `y` smallint(6) DEFAULT NULL,
  `w` smallint(6) DEFAULT NULL,
  `h` smallint(6) DEFAULT NULL,
  `phi` smallint(6) DEFAULT NULL,
  `xy_dist_log10x1000` smallint(6) DEFAULT NULL,
  `is_inferred` tinyint(1) DEFAULT NULL,
  `has_interacted` smallint(6) DEFAULT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=1588454 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci KEY_BLOCK_SIZE=16;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `ROI_19`
--

DROP TABLE IF EXISTS `ROI_19`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `ROI_19` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `t` int(11) DEFAULT NULL,
  `x` smallint(6) DEFAULT NULL,
  `y` smallint(6) DEFAULT NULL,
  `w` smallint(6) DEFAULT NULL,
  `h` smallint(6) DEFAULT NULL,
  `phi` smallint(6) DEFAULT NULL,
  `xy_dist_log10x1000` smallint(6) DEFAULT NULL,
  `is_inferred` tinyint(1) DEFAULT NULL,
  `has_interacted` smallint(6) DEFAULT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=1588301 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci KEY_BLOCK_SIZE=16;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `ROI_2`
--

DROP TABLE IF EXISTS `ROI_2`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `ROI_2` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `t` int(11) DEFAULT NULL,
  `x` smallint(6) DEFAULT NULL,
  `y` smallint(6) DEFAULT NULL,
  `w` smallint(6) DEFAULT NULL,
  `h` smallint(6) DEFAULT NULL,
  `phi` smallint(6) DEFAULT NULL,
  `xy_dist_log10x1000` smallint(6) DEFAULT NULL,
  `is_inferred` tinyint(1) DEFAULT NULL,
  `has_interacted` smallint(6) DEFAULT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=1588515 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci KEY_BLOCK_SIZE=16;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `ROI_20`
--

DROP TABLE IF EXISTS `ROI_20`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `ROI_20` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `t` int(11) DEFAULT NULL,
  `x` smallint(6) DEFAULT NULL,
  `y` smallint(6) DEFAULT NULL,
  `w` smallint(6) DEFAULT NULL,
  `h` smallint(6) DEFAULT NULL,
  `phi` smallint(6) DEFAULT NULL,
  `xy_dist_log10x1000` smallint(6) DEFAULT NULL,
  `is_inferred` tinyint(1) DEFAULT NULL,
  `has_interacted` smallint(6) DEFAULT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=1473205 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci KEY_BLOCK_SIZE=16;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `ROI_3`
--

DROP TABLE IF EXISTS `ROI_3`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `ROI_3` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `t` int(11) DEFAULT NULL,
  `x` smallint(6) DEFAULT NULL,
  `y` smallint(6) DEFAULT NULL,
  `w` smallint(6) DEFAULT NULL,
  `h` smallint(6) DEFAULT NULL,
  `phi` smallint(6) DEFAULT NULL,
  `xy_dist_log10x1000` smallint(6) DEFAULT NULL,
  `is_inferred` tinyint(1) DEFAULT NULL,
  `has_interacted` smallint(6) DEFAULT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=1564300 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci KEY_BLOCK_SIZE=16;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `ROI_4`
--

DROP TABLE IF EXISTS `ROI_4`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `ROI_4` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `t` int(11) DEFAULT NULL,
  `x` smallint(6) DEFAULT NULL,
  `y` smallint(6) DEFAULT NULL,
  `w` smallint(6) DEFAULT NULL,
  `h` smallint(6) DEFAULT NULL,
  `phi` smallint(6) DEFAULT NULL,
  `xy_dist_log10x1000` smallint(6) DEFAULT NULL,
  `is_inferred` tinyint(1) DEFAULT NULL,
  `has_interacted` smallint(6) DEFAULT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=1583944 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci KEY_BLOCK_SIZE=16;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `ROI_5`
--

DROP TABLE IF EXISTS `ROI_5`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `ROI_5` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `t` int(11) DEFAULT NULL,
  `x` smallint(6) DEFAULT NULL,
  `y` smallint(6) DEFAULT NULL,
  `w` smallint(6) DEFAULT NULL,
  `h` smallint(6) DEFAULT NULL,
  `phi` smallint(6) DEFAULT NULL,
  `xy_dist_log10x1000` smallint(6) DEFAULT NULL,
  `is_inferred` tinyint(1) DEFAULT NULL,
  `has_interacted` smallint(6) DEFAULT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=1588526 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci KEY_BLOCK_SIZE=16;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `ROI_6`
--

DROP TABLE IF EXISTS `ROI_6`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `ROI_6` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `t` int(11) DEFAULT NULL,
  `x` smallint(6) DEFAULT NULL,
  `y` smallint(6) DEFAULT NULL,
  `w` smallint(6) DEFAULT NULL,
  `h` smallint(6) DEFAULT NULL,
  `phi` smallint(6) DEFAULT NULL,
  `xy_dist_log10x1000` smallint(6) DEFAULT NULL,
  `is_inferred` tinyint(1) DEFAULT NULL,
  `has_interacted` smallint(6) DEFAULT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=1588389 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci KEY_BLOCK_SIZE=16;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `ROI_7`
--

DROP TABLE IF EXISTS `ROI_7`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `ROI_7` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `t` int(11) DEFAULT NULL,
  `x` smallint(6) DEFAULT NULL,
  `y` smallint(6) DEFAULT NULL,
  `w` smallint(6) DEFAULT NULL,
  `h` smallint(6) DEFAULT NULL,
  `phi` smallint(6) DEFAULT NULL,
  `xy_dist_log10x1000` smallint(6) DEFAULT NULL,
  `is_inferred` tinyint(1) DEFAULT NULL,
  `has_interacted` smallint(6) DEFAULT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=1570454 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci KEY_BLOCK_SIZE=16;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `ROI_8`
--

DROP TABLE IF EXISTS `ROI_8`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `ROI_8` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `t` int(11) DEFAULT NULL,
  `x` smallint(6) DEFAULT NULL,
  `y` smallint(6) DEFAULT NULL,
  `w` smallint(6) DEFAULT NULL,
  `h` smallint(6) DEFAULT NULL,
  `phi` smallint(6) DEFAULT NULL,
  `xy_dist_log10x1000` smallint(6) DEFAULT NULL,
  `is_inferred` tinyint(1) DEFAULT NULL,
  `has_interacted` smallint(6) DEFAULT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=1588509 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci KEY_BLOCK_SIZE=16;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `ROI_9`
--

DROP TABLE IF EXISTS `ROI_9`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `ROI_9` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `t` int(11) DEFAULT NULL,
  `x` smallint(6) DEFAULT NULL,
  `y` smallint(6) DEFAULT NULL,
  `w` smallint(6) DEFAULT NULL,
  `h` smallint(6) DEFAULT NULL,
  `phi` smallint(6) DEFAULT NULL,
  `xy_dist_log10x1000` smallint(6) DEFAULT NULL,
  `is_inferred` tinyint(1) DEFAULT NULL,
  `has_interacted` smallint(6) DEFAULT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=1587983 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci KEY_BLOCK_SIZE=16;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `ROI_MAP`
--

DROP TABLE IF EXISTS `ROI_MAP`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `ROI_MAP` (
  `roi_idx` smallint(6) DEFAULT NULL,
  `roi_value` smallint(6) DEFAULT NULL,
  `x` smallint(6) DEFAULT NULL,
  `y` smallint(6) DEFAULT NULL,
  `w` smallint(6) DEFAULT NULL,
  `h` smallint(6) DEFAULT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci KEY_BLOCK_SIZE=16;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `START_EVENTS`
--

DROP TABLE IF EXISTS `START_EVENTS`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `START_EVENTS` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `t` int(11) DEFAULT NULL,
  `event` char(100) DEFAULT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=2 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci KEY_BLOCK_SIZE=16;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `VAR_MAP`
--

DROP TABLE IF EXISTS `VAR_MAP`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `VAR_MAP` (
  `var_name` char(100) DEFAULT NULL,
  `sql_type` char(100) DEFAULT NULL,
  `functional_type` char(100) DEFAULT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci KEY_BLOCK_SIZE=16;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping routines for database 'ETHOSCOPE_285_db'
--
/*!40103 SET TIME_ZONE=@OLD_TIME_ZONE */;

/*!40101 SET SQL_MODE=@OLD_SQL_MODE */;
/*!40014 SET FOREIGN_KEY_CHECKS=@OLD_FOREIGN_KEY_CHECKS */;
/*!40014 SET UNIQUE_CHECKS=@OLD_UNIQUE_CHECKS */;
/*!40101 SET CHARACTER_SET_CLIENT=@OLD_CHARACTER_SET_CLIENT */;
/*!40101 SET CHARACTER_SET_RESULTS=@OLD_CHARACTER_SET_RESULTS */;
/*!40101 SET COLLATION_CONNECTION=@OLD_COLLATION_CONNECTION */;
/*!40111 SET SQL_NOTES=@OLD_SQL_NOTES */;

-- Dump completed on 2025-06-30 13:46:50
