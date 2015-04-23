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


	ts <- as.ts(zoo(d,d[,t]))
	d <- as.data.table(ts)
	d[,t := index(ts)]
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

y <- cumsum(rnorm(N))
t <- sort(jitter(1:N))
y2 <- y[N] + cumsum(rnorm(N))
t2 <- sort(jitter((2*N + 1 ): (3*N))) 

y <- c(y,y2)
t <- 1000 + c(t,t2)

d <- data.table(y,t)

	
	d[, V1:=rnorm(.N)]
	d[, V2:=rnorm(.N)]
	d[, V3:=rnorm(.N)]
#~ 	d[, V4:=rnorm(.N)]
#~ 	d[, V5:=rnorm(.N)]
#~ 	d[, V1:=ifelse(rnorm(.N) > 0, "a", "b")]
#~ 	d[, V2:=ifelse(rnorm(.N) > 0, "a", "b")]
#~ 	d[, V3:=ifelse(rnorm(.N) > 0, "a", "b")]
	d[, V4:=ifelse(rnorm(.N) > 0, "a", "b")]
	d[, V5:=ifelse(rnorm(.N) > 0, "c", "v")]
#~ 	setkey(d, "V5")
################################

 
plot(y ~ t, d, type='l', xlim=c(0,t[length(t)]),lwd=2)

dt <- interpolateROIData(d, fs)


#~ o <- microbenchmark(
#~ m1 = interpolateROIData(d, fs,interpolate),
#~ m2 = interpolateROIData(d, fs,interpolate2), times=10)





