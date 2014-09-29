#!/usr/bin/env python2
# -*- coding: utf-8 -*-
#
#       pvg_options.py
#       
#       Copyright 2011 Giorgio Gilestro <giorgio@gilest.ro>
#       
#       This program is free software; you can redistribute it and/or modify
#       it under the terms of the GNU General Public License as published by
#       the Free Software Foundation; either version 2 of the License, or
#       (at your option) any later version.
#       
#       This program is distributed in the hope that it will be useful,
#       but WITHOUT ANY WARRANTY; without even the implied warranty of
#       MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#       GNU General Public License for more details.
#       
#       You should have received a copy of the GNU General Public License
#       along with this program; if not, write to the Free Software
#       Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston,
#       MA 02110-1301, USA.
#       
#       

import wx, os
from pvg_common import options
import wx.lib.filebrowsebutton as filebrowse


class partial: #AKA curry
    '''
    This functions allows calling another function upon event trigger and pass arguments to it
    ex buttonA.Bind (wx.EVT_BUTTON, partial(self.Print, 'Hello World!'))
    '''

    def __init__(self, fun, *args, **kwargs):
        self.fun = fun
        self.pending = args[:]
        self.kwargs = kwargs.copy()

    def __call__(self, *args, **kwargs):
        if kwargs and self.kwargs:
            kw = self.kwargs.copy()
            kw.update(kwargs)
        else:
            kw = kwargs or self.kwargs

        return self.fun(*(self.pending + args), **kw)

class optionsFrame(wx.Frame):
    def __init__(self, parent, ID=-1, title='pySolo Video Options', pos=wx.DefaultPosition,
        size=(640,480), style=wx.DEFAULT_FRAME_STYLE
            ):
        
        wx.Frame.__init__(self, parent, ID, title, pos, size, style)
        
        pp = wx.Panel(self, -1)
        self.optpane = wx.Treebook(pp, -1, style= wx.BK_DEFAULT)

        # Now make a bunch of panels for the list book
        for section in options.getOptionsGroups():
            # The first item of the list is the main Panel
            tbPanel = self.makePanel(self.optpane, section)
            self.optpane.AddPage(tbPanel, section)

            #for option in options.getOptionsNames(section):
            #    # All the following ones are children
            #    tbPanel = self.makePanel(self.optpane, option)
            #    self.optpane.AddSubPage(tbPanel, option)


        btSave = wx.Button(pp, wx.ID_SAVE)
        btCancel = wx.Button(pp, wx.ID_CANCEL)
        btSave.Bind(wx.EVT_BUTTON, self.onSaveOptions)
        btCancel.Bind(wx.EVT_BUTTON, self.onCancelOptions)
        self.Bind(wx.EVT_CLOSE, self.onCancelOptions)


        btSz = wx.BoxSizer(wx.HORIZONTAL)
        btSz.Add (btCancel)
        btSz.Add (btSave)

        sz = wx.BoxSizer(wx.VERTICAL)
        sz.Add (self.optpane, 1, wx.EXPAND)
        sz.Add (btSz, 0, wx.ALIGN_RIGHT | wx.ALL, 10)

        pp.SetSizer(sz)

        # This is a workaround for a sizing bug on Mac...
        wx.FutureCall(100, self.__adjustSize)


        for i in range(0,len(self.optpane.Children)-1):
            self.optpane.ExpandNode(i)

    def __adjustSize(self):
        '''
        Apparently this is needed as workaround for a sizing bug on Mac.
        '''
        self.optpane.GetTreeCtrl().InvalidateBestSize()
        self.optpane.SendSizeEvent()

    def makePanel(self, parent, name):
        """
        """
        tp = wx.Panel(parent, -1,  style = wx.TAB_TRAVERSAL)

        self.virtualw = wx.ScrolledWindow(tp)
        
        sz1 = wx.BoxSizer(wx.VERTICAL)

        titleFont = wx.Font(10, wx.SWISS, wx.NORMAL, wx.BOLD)
        items = []

        for option in options.getOptionsNames(name):
            option_name = option
            option_value= str(options.GetOption(option_name))
            option_description = options.getOptionDescription(option_name)

            items.append ( wx.StaticText(self.virtualw, -1, '\nSet value of the variable: %s' % option_name))
            items[-1].SetFont(titleFont)
            items.append (  wx.StaticText(self.virtualw, -1, option_description) )

            if "FOLDER" in option_name.upper():
                items.append ( filebrowse.DirBrowseButton(self.virtualw, -1, size=(400, -1), changeCallback = partial(self.__saveValue, option_name), startDirectory="."  ))
                items.append ( (wx.StaticLine(self.virtualw), 0, wx.EXPAND|wx.TOP|wx.BOTTOM, 5 ))
                
            
            else: #for boolean first choice is always True, second choice always False
                
                items.append ( wx.TextCtrl (self.virtualw, -1, value=option_value))
                items[-1].Bind (wx.EVT_TEXT, partial (self.__saveValue, option_name) )
                items.append ( (wx.StaticLine(self.virtualw), 0, wx.EXPAND|wx.TOP|wx.BOTTOM, 5 ))
        
        
        
        sz1.AddMany (items)
        self.virtualw.SetSizer(sz1)
        sz1.Fit(self.virtualw)
        
        self.virtualw.SetScrollRate(20,20)
        TreeBookPanelSizer = wx.BoxSizer()
        TreeBookPanelSizer.Add(self.virtualw,  1, wx.GROW | wx.EXPAND, 0)
        tp.SetSizer(TreeBookPanelSizer)
        return tp
        
    def __saveValue(self, key, event):
        """
        """
        value = event.GetString()
        options.SetOption( key, value )
        
        
    def onCancelOptions(self, event):
        """
        """
        self.Destroy()
        
    def onSaveOptions(self, event):
        """
        """
        options.Save()
        self.Close()



class MyApp(wx.App):
    def OnInit(self):
        self.options_frame =  optionsFrame(None)
        self.options_frame.Show(True)
        return True


if __name__ == '__main__':


    # Run program
    app=MyApp()
    app.MainLoop()



