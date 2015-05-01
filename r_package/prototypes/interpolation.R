rm(list=ls())
library(data.table)
library(pracma)
library(zoo)
library(microbenchmark)

N <- 50000
fs <- 1
set.seed(1)


interpolate <- function(t, yy, t_out){
	if(is.numeric(yy)){
		return(interp1(t, yy, t_out, "linear"))
	}
	
	else{
			yy <- as.factor(yy)
			levs <- levels(yy)
			yy <- unclass(yy)
			attr(yy, "levels") <- NULL
			out <- interp1(t, yy, t_out, "nearest")
			out <- as.factor(levs[out])
			return(out)
		}
}

interpolateROIData <- function(data, fs){
	d <- copy(data)
	ori_keys <- key(d)
	
	sampling_period <- 1/fs
	d[, t_round := sampling_period * round(d[,t] /sampling_period)]
	setkey(d, "t_round")
	# FIXME!
	d <- d[,lapply(.SD,mean),by=t_round]
	
	
	
	
	# all possible required output times
	t_out <- seq(from=d[1,t_round], to=d[.N,t_round], by=sampling_period)
	
	t_to_interpolate <- setdiff(t_out, d$t_round)
	
	to_interpolate_dt <- d[t_round==t_to_interpolate]
	
	missing_points <- lapply(d, interpolate, t=d[,t], t_out=t_to_interpolate)
	
	
	missing_points <- as.data.table(missing_points)
	missing_points[ , t_round := t_to_interpolate]
 	setkey(missing_points, "t_round")
 	d <- rbind(missing_points, d)
 	
	# we ensure the dt is time sorted
	setkey(d, "t_round")
	d$t_round <- NULL
	
	# we restitute old keys
	setkeyv(d, ori_keys)
	return(d)

}





###########################################################################
FILE <- "/data/psv_results/2015-04-17_17-06-49_00016dfce6e94dee9bb1a845281b086e.db"

d <- loadROIsFromFile(FILE,rois=2)
d <- d[t < 300 | t > 700]

t = system.time(di <- interpolateROIData(d, fs))
print(t)



#~ o <- microbenchmark(
#~ m1 = interpolateROIData(d, fs,interpolate),
#~ m2 = interpolateROIData(d, fs,interpolate2), times=10)





