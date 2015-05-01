rm(list=ls())
library(risonno)
library(data.table)
library(ggplot2)

#@include 
NULL
#' Read multiple files into a single data table
#' 
#' This function is used to conveniently put together data from different monitors/experiemnts.
#'
#' @param files either a vector of files or a data.table (or data frame). When \code{files} is a data.table, it \textbf{must} have, at least, a column named `file'. 
#' The other columns can be used to map experimental variables (e.g. treatment/genotype/...) to each file.
#' @param ... further arguments for \code{\link{loadROIsFromFile}}
#' @return A data.table where each row is a unique measurment (i.e. one position at one time, for one animal).
#' @note When loading multiple files using \code{loadMultipleFiles}, the filename (i.e. column `file') is used as additional key for the data.table.
#' Conceptually, this means that time series are for every combination of ROI id (animal) \textbf{and} file name (experiment).
#' @examples
#' \dontrun{
#' # The paths of the four files we want to load
#' path <- c(
#' 		"2015-04-17_17-06-49_00016dfce6e94dee9bb1a845281b086e.db",
#' 		"2015-04-17_17-09-18_00026dfce6e94dee9bb1a845281b086e.db",
#' 		"2015-04-17_17-10-32_00036dfce6e94dee9bb1a845281b086e.db",
#' 		"2015-04-17_17-11-11_00046dfce6e94dee9bb1a845281b086e.db"
#' 	)
#' # In the same order, experiemental conditions that were applied to these four experiements.
#' conditions <- as.factor(c("ctrl", "cond_1", "ctrl", "cond_1"))
#' # We build a table where every "path" maps a conditions.
#' ref <- data.table(path,conditions)
#' # We load rois 1 to 16 from all the files.Since Experiments have 
#' # not started at exactly the same time, we align them to a reference hour (9:00).
#' # We also average (interpolate) every 5s of data
#' dt <- loadMultipleFiles(files=ref, rois=c(1:16), reference_hour = 9, FUN=interpolateROIData, fs=1/5.)

#' @seealso \code{\link{loadROIsFromFile}} to load single files.
#' @export
loadMultipleFiles <- function(files, ...){
	path <- files
	file_dt <- as.data.table(path)
	if(!("path" %in% colnames(file_dt)))
		stop("file_dt should be a dataframe with, at least, a column names 'path'")
	
	file_dt[,file := basename(path)]
	setkey(file_dt, file)
	#print(file_dt[,file])
	dup <- anyDuplicated(file_dt[,file])
	if(dup != 0)
		stop(
			sprintf("Duplicated file name: %s",file_dt[dup,file])
			)
			
	l_dt <- lapply(file_dt[,path], function(x){
			loadROIsFromFile(x, add_file_name=T, ...)
		})
	
	if(length(unique(lapply(l_dt,key))) > 1){
		stop("Data tables do not have the same keys")
		}
	keys <- key(l_dt[[1]])
	
	out <- rbindlist(l_dt)
	rm(l_dt)
	
	setkeyv(out, keys)
	out <- file_dt[out]
	setkeyv(out, keys)
	return(out)
	} 

path <- c(
	"/data/psv_results/00016dfce6e94dee9bb1a845281b086e/GGSM-001/2015-04-17_17-06-49/2015-04-17_17-06-49_00016dfce6e94dee9bb1a845281b086e.db",
	"/data/psv_results/00026dfce6e94dee9bb1a845281b086e/GGSM-002/2015-04-17_17-09-18/2015-04-17_17-09-18_00026dfce6e94dee9bb1a845281b086e.db",
 	"/data/psv_results/00036dfce6e94dee9bb1a845281b086e/GGSM-003/2015-04-17_17-10-32/2015-04-17_17-10-32_00036dfce6e94dee9bb1a845281b086e.db",
 	"/data/psv_results/00046dfce6e94dee9bb1a845281b086e/GGSM-004/2015-04-17_17-11-11/2015-04-17_17-11-11_00046dfce6e94dee9bb1a845281b086e.db"
	)

conditions <- as.factor(c("ctrl", "quinine", "camphor_1", "camphor_2"))
#~ conditions <- as.factor(c("ctrl", "quinine"))#, "camphor_1", "camphor_2"))

ref <- data.table(path,conditions)


dt <- loadMultipleFiles(files=ref, rois=c(2:15,17:31), reference_hour = 9, FUN=interpolateROIData, fs=1/5.)



activity <- function(x,y){
	comp = x + 1i*y
	distance <- c(0, abs(diff(comp)))
	return(distance)
}
# compute activity for each ROI in place



dt[,activity:=activity(x,y) , by=key(dt)]


tp <- dt[,list(activity=mean(activity)) , by=c("t","conditions")]

setkey(tp,t)

tp[, filtered_act := filter(activity,rep(1/241,241)), by=c("conditions")]
tp[, h:= t/3600]
ggplot(data = tp, aes(x=h, y=filtered_act, colour=as.factor(conditions))) + geom_line() + geom_vline(xintercept = 1:14*12)

dt[, roi_id := as.numeric(roi_id)]

dt[,x_rel:=ifelse(roi_id > 16, 1-x,x)]
dt[,x2:=ifelse(x_rel > .95,.95,x_rel) ]
ggplot(dt[t>5*24*3600], aes(x=x2)) + geom_density(aes(group=conditions, colour=conditions, fill=conditions), alpha=0.3)
ggplot(dt, aes(x=x2)) + geom_density(aes(group=conditions, colour=conditions, fill=conditions), alpha=0.3)
