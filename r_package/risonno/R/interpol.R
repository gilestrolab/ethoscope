NULL

#' Resample data from an area matrix.
#' 
#' This function returns position from reads at a regular time interval.
#' This is perfomed through linear interpolation.
#' @param m a numerical matrix corresponding to an area.
#' @param h the desired resampling frequency in Hz.
#' @param minRow an integer defining the minimal number of reads. If less than minRow reads are present in m, the function returns an empty matrix.
#' @return A new area matrix.
#' @note The new matrix will likely have a different number of rows than the source matrix. 
#' The attributes of the source matrix are copied to the new matrix.
#' @examples
#' #TODO
#'
#@seealso \code{\link{ubitMedianFilter}} to smooth data (before interpolation).
#' @export

interpolateTS <- function(m,h=30,minRow=11){
	
	if(!any(class(m) == "matrix"))
		stop("This function works with a matrix. If you have a a list of matrices, use lapply to call this function on each element of the list. See examples for details.")
		
	
	if(attributes(m)$tags.isHomogenous)
		warning("This data matrix has already been resampled.")
		
	if(nrow(m) >= minRow & attributes(m)$tags.hasEnoughPoints){
		t0 <- m[1,'time']
		tf <- m[nrow(m),'time']
		dt <- (tf-t0)/1000
		n <- round(h*dt)
		t_out <- seq(from = t0, to = tf, length.out=n)
		
		xx <- approx(x=m[,'time'], y=m[,'X'],xout=t_out)$y

		yy <- approx(x=m[,'time'], y=m[,'Y'],xout=t_out)$y

		L <- approx(x=m[,'time'], y=m[,'L'],xout=t_out)$y
		
		T <- approx(x=m[,'time'], y=m[,'Territory'],xout=t_out,method='const')$y
		
		mm<-cbind(T,xx,yy,t_out,L)
		atr <- attributes(m)
		atr$dim <- attributes(mm)$dim
		attributes(mm) <-atr
		attributes(mm)$tags.hasEnoughPoints <- TRUE
		}
	else{
		mm <- m
		attributes(mm)$tags.hasEnoughPoints <- FALSE
	}
	attributes(mm)$tags.isHomogenous <- TRUE
	mm
}
