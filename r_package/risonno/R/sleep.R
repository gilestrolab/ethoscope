#@include 
NULL
#' TODO
#' 
#' T
#'
#' @param data the data (i.e a data.table) from a \emph{single} ROI. It must contain, at least,
#' the columns `t`, `x` and `y`.
#' @param fs (in Hz) the frequency to which the data is resampled, prior to analysis.
#' @param activity_threshold the activity over which an animal is scored as `moving'. 
#' The activity is the total covered distance in \code{time_window_length} (expressed proportion of the ROI width).
#' @param time_window_length The number of seconds in which activity threshold is applied.
#' @param min_time_immobile the minimal duration (in s) after wich an immobile an animal is scored as `asleep'.
#' @return A data table similar to \code{data} with additionnal variables/annotations (i.e. `activity', `moving', `asleep').
#' @note The resulting data will only have one data point every \code{time_window_length} seconds.

#' @examples
#' # We load samples from the package data
#' file <- loadSampleData("validation.db")
#' # We would like only ROI #2 from this file
#' map <- data.frame(path=file, roi_id=2)
#' dt <- loadPsvData(map)
#' sleep_dt <-  sleepAnalysis(dt)
#' # A more liekely scenario, we load ROIs 5 to 10, 
#' # apply sleep analysis in combination with loadPsvData.
#' # this means we apply the function to all rois just after they are being loaded.
#' map <- data.frame(path=file, roi_id=5:10)
#' dt <- loadPsvData(map,FUN=sleepAnalysis)
#' 
#' @seealso \code{\link{loadPsvData}} to load data and optionnaly apply analysis on the fly.
#' @export
sleepAnalysis <- function(data,
			time_window_length=10, #s
			min_time_immobile=60*5, #s
			motion_classifier_FUN=totalWlkdDistClassif,
			...
			){ 
	d <- copy(data)
	ori_keys <- key(d)
	
	d <- curateSparseRoiData(d)
	
	
	d[, t_round := time_window_length * floor(d[,t] /time_window_length)]
	setkeyv(d, "t_round")

	d_small <- motion_classifier_FUN(d,...)
	d_small <- unique(d_small[d])
	
	d_small[,t:=t_round]
	d_small$t_round <- NULL
	setkeyv(d_small,"t")
	

	t_out <- seq(from=d_small[1,t], to=d_small[.N,t], by=time_window_length)
	
	
	d_small <- merge(d_small, data.table(t=t_out,key="t"),all=T)
	d_small[,moving := ifelse(is.na(moving), F, moving)]
	d_small[,asleep := sleep_contiguous(moving,1/time_window_length)]
	
	d_small <- d_small[,lapply(.SD,na.locf,na.rm=F)]
	
	setkeyv(d_small, ori_keys)
	
	d_small
	}


totalWlkdDistClassif <- function(data,activity_threshold=.03){
	d <- copy(data)
	d[,activity := activity(x,y)]
	d[,ar := ifelse(w > h, w/h,h/w)]
	d[,ar_diff := abs(c(NA,diff(ar)))]
	d[,phi_diff := abs(c(NA,diff(cos(phi/180))))]
	d_small <- d[,list(
						activity = sum(activity),
						ar_diff = sum(ar_diff),
						phi_diff = sum(phi_diff),
						max_velocity = max(activity/c(Inf,diff(t)))
						), by="t_round"]
	
	d_small[, moving :=  ifelse(activity > activity_threshold, TRUE,FALSE)]
#'	d$activity <- NULL
#'	d$ar <- NULL
#'	d$ar_diff <- NULL
#'	d$phi_diff <- NULL
#'	
	d_small
	}


activity <- function(x,y){
	comp = x + 1i*y
	distance <- c(0, abs(diff(comp)))
	return(distance)
}


sleep_contiguous <- function(moving,fs,min_valid_time=5*60){
	min_len <- fs * min_valid_time
	r_sleep <- rle(!moving)
	valid_runs <-  r_sleep$length > min_len 
	r_sleep$values <- valid_runs & r_sleep$value
	inverse.rle(r_sleep)
}

#' remove data points when the time serie is too sparse
curateSparseRoiData <- function(
	data,
	window=60,#s
	min_points=20#
	){
	d <- copy(data)
	d[, t_w := window * floor(t/window)]
	sparsity <- d[, t_w := window * floor(t/window)]
	d[,sparsity := .N,by=t_w]
	d[,sparsity := .N,by=t_w]
	d <- d[sparsity >min_points,]
	d$t_w <- NULL
	d$sparsity <- NULL
	d
	}
	
