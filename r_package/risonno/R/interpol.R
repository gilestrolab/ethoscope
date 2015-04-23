NULL

#' Resample ROI data to a regular multivariate time series.
#' 
#' This function performs linear interpolation in order to obtain a regular time series from a possibly irregular one.
#'
#' @param d a dataframe containing a time column (\code{d$t}) and one or several columns for recorded variables.
#' @param fs the desired resampling frequency, in Hz. By default, the median empirical sampling rate is used.
#' @param min_n_point an integer defining the minimal number of reads. If fewer reads are present in \code{d}, the function will through an error.
#' @return A new dataframe with the same columns as \code{d}.
#' @note The exact time stamp of every data point is may depend, for instance, on the acquisition device's processing time.
#' This it quite likely to result in irregular time series between devices.
#' @examples
#' \dontrun{
#' FILE <- "result.db"
#' # Load the three first ROIs
#' ldfs <- loadROIsFromFile(FILE, rois=1:3)
#' ###### Simple example resampling the first ROI from t=0 at 5Hz:
#' d <- ldfs$ROI_1
#' new_d <- interpolateROIData(d, fs=1, start_time=0)
#' head(new_d)
#' ###### Now resample from 0 to the last time point available at 1Hz, all dataframes.
#' First, we get the last overall time point:
#' last_time_point <- max(sapply(ldfs, function(d){d$t[length(d$t)]}))
#' # then we use lapply to apply this function to all dataframes in the list
#' resampled_dfs <- lapply(ldfs, interpolateROIData,  fs=1, start_time=0, stop_time=last_time_point)
#' head(resampled_dfs$ROI_1)
#'	}
#' @seealso \code{\link{loadROIsFromFile}} in order to load ROI data.
#' @export

interpolateROIData <- function(data, fs){
	d <- copy(data)
	ori_keys <- key(d)
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


interpolateROIData_old <- function(d,min_n_points=11, fs=NA, start_time=0, stop_time=NA){	
	
	if(nrow(d) < min_n_points){
		warning("This data table does not have enough rows to be resampled. NULL returned")
		return(NULL)
		}
		
	t0 <- d[1,t]
	tf <- d[.N,t]
	if(!is.na(start_time))
		t0 <- start_time
	if(!is.na(stop_time))
		tf <- stop_time
	
	
	if (is.na(fs))
		fs <- median(diff(d[,t]))
	
	
	dt <- (tf-t0)

	t_out <- seq(from = t0, to = tf, by=1/fs)
	bin_length <- 1/fs
	
	time_in_bin <- bin_length * round(d[,t] /bin_length)
	
	variables_to_interpol <- colnames(d)[colnames(d) != "t"]
	new_d <- lapply(variables_to_interpol, function(xx){
		var_class <- class(d[,get(xx)])
		method <- ifelse(var_class == "numeric","linear","constant")
		

		if(method == "numeric")
			 binned_dt = d[, list(t=mean(t), y=mean(get(xx))), by=time_in_bin]
		else
			binned_dt = d[, list(t=mean(t), y=get(xx)[1]), by=time_in_bin]
			#fixme
		if(var_class == "character"){
			binned_dt[,y := as.factor(y) ]
			var_class <- "factor"
		}
				

		 
		y_out <- approx(x=binned_dt[,t], y=binned_dt[,y],xout=t_out, method=method, rule=c(2,2))$y
		 
		if(var_class == "factor")
			y_out <- as.factor(levels(binned_dt[,y])[y_out[1]])
		
		y_out <- as(y_out, var_class)
		return(y_out)
		})
	
	names(new_d) <- variables_to_interpol
	
	new_dt <- as.data.table(data.frame(t=t_out, new_d))
	
	
	
	
	
	return(new_dt)
}
