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

interpolateROIData <- function(d,min_n_points=11, fs=NA, start_time=NA, stop_time=NA){
			
	if(nrow(d) < min_n_points)
		stop("This dataframe does not have enough rows to be resampled")
		t0 <- d[1,'t']
		tf <- d[nrow(d),'t']
		if(!is.na(start_time))
			t0 <- start_time
		if(!is.na(stop_time))
			tf <- stop_time
		
		
		if (is.na(fs))
			fs <- median(diff(d[,"t"]))

		dt <- (tf-t0)

		t_out <- seq(from = t0, to = tf, by=1/fs)
		
		t_in <- d[,"t"]
		
		
		new_d <- lapply(d[,colnames(d) != "t"],
			function(v){
				approx(x=t_in, y=v,xout=t_out)$y
			}
		)
		new_d <- data.frame(t=t_out,new_d)
		return(new_d)
}
