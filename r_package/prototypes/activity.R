library(risonno)
FILE <- "~/Desktop/test2.db"



out <- loadROIsFromFile(FILE, FUN=function(d)max(d$t))
max_t <- max(unlist(out))
roi_dfs <- loadROIsFromFile(FILE, 
	FUN=interpolateROIData, start=0,
	stop = max_t, fs=1)

activity <- function(d){
	comp = d$x + 1i*d$y
	distance <- c(0, abs(diff(comp)))
	d$activity <- distance
	return(d)
}


roi_dfs <- lapply(roi_dfs, activity)

pdf(w=16,h=9)
lapply(names(roi_dfs), function(n) {
	
	d <- roi_dfs[[n]]
	tt <- d$t/3600;
	
	y <- filter(d$activity, rep(1,601))
	sparse_idx <- seq(0, length(tt), length.out=1e4)
	tt <- tt[sparse_idx]
	y <- y[sparse_idx]

	plot(y ~ tt, type='l',ylim=c(0,50),
	xlab="time(h)",
	ylab="Activity (tube lenght walked in 10min)",
	main=n)
	abline(v = 40.25 + -10 :10 * 12, col="blue", lwd=3, lty=2)
	return(NULL)
	})
dev.off()

pdf("test.pdf", w=16,h=9)
lapply(names(roi_dfs), function(n) {
	
	d <- roi_dfs[[n]]
	tt <- d$t/3600;
	
	y <- filter(d$activity, rep(1,61)) # on min

 	hist(log10(y), nclass=100, xlab="log10(Activity) (lenght of tube/min)",freq=F,xlim=c(0,1), ylim=c(0,1), main=n)
	#plot(density(na.omit(y)), xlab="Activity (lenght of tube/min)",freq=F,xlim=c(0,10), log="y")

	abline(v = .1, col="blue", lwd=3, lty=2)
	return(NULL)
	})
dev.off()
