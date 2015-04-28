rm(list=ls())
library(data.table)
library(pracma)
library(zoo)
library(microbenchmark)

N <- 50000
fs <- 1/10
set.seed(1)

average <- function(x){
	if(is.numeric(x)){
		return(mean(x))
		}
	else{
		#fixme
		return(x[1])
		}
	}

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
	print(ori_keys)
	sampling_period <- 1/fs
	d[, t := sampling_period * round(d[,t] /sampling_period)]
	setkey(d, "t")

	d <- d[,lapply(.SD,average),by=t]
	data.table(t2=seq(from=d[1,t2], to=d[.N,t2], by=sampling_period))

	ts <- as.ts(zoo(d,d[,t]))
	d <- as.data.table(ts)
	d[,t :=, to = ]
	setkey(d, "t")

	missing_idxs <- apply(is.na(d),1,any)
	
	missing_points <- d[missing_idxs,t]
 	dd <- as.data.table(lapply(d, interpolate, t=d[,t], t_out=missing_points))
 	setkey(dd, "t")
	
	d[missing_idxs,] <- dd

	setkeyv(d, ori_keys)
	return(d)

}





###########################################################################
FILE <- "/data/psv_results/2015-04-17_17-06-49_00016dfce6e94dee9bb1a845281b086e.db"
#~ conditions <- cbind(roi_id=1:32, expand.grid(treatment=c(T,F), genotype=LETTERS[1:4]))
#~ dt <- loadROIsFromFile(FILE, FUN=interpolateROIData, fs=1/10, condition_df = conditions)
dd <- loadROIsFromFile(FILE)
d = dd[roi_id==2,]
#~ 	
#~ 	d[, V1:=rnorm(.N)]
#~ 	d[, V2:=rnorm(.N)]
#~ 	d[, V3:=rnorm(.N)]
#~ 	d[, V4:=rnorm(.N)]
#~ 	d[, V5:=rnorm(.N)]
#~ 	d[, V1:=ifelse(rnorm(.N) > 0, "a", "b")]
#~ 	d[, V2:=ifelse(rnorm(.N) > 0, "a", "b")]
#~ 	d[, V3:=ifelse(rnorm(.N) > 0, "a", "b")]
#~ 	d[, V4:=ifelse(rnorm(.N) > 0, "a", "b")]
#~ 	d[, V5:=ifelse(rnorm(.N) > 0, "c", "v")]
#~ 	setkey(d, "V5")
################################



di <- interpolateROIData(d, fs)


#~ o <- microbenchmark(
#~ m1 = interpolateROIData(d, fs,interpolate),
#~ m2 = interpolateROIData(d, fs,interpolate2), times=10)





