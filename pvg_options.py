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

class pvg_OptionsPanel(wx.Panel):
    def __init__(self, parent):
        wx.Panel.__init__(self, parent, wx.ID_ANY)
        self.parent = parent
        
        ########
        mainSizer = wx.BoxSizer(wx.HORIZONTAL)
        optionsList = [key for key in options.defaultOptions]
        self.tb = wx.ListBox(self, wx.ID_ANY, choices=optionsList, style=wx.LB_SINGLE)
        self.Bind(wx.EVT_LISTBOX, self.onSelect, self.tb)
        #########
        
        #########
        self.sp = wx.Panel(self, wx.ID_ANY)
        sz1 = wx.BoxSizer(wx.VERTICAL)
        
        sz2 = wx.BoxSizer(wx.VERTICAL)
        titleFont = wx.Font(10, wx.SWISS, wx.NORMAL, wx.BOLD)
        items = []
        self.input = []

        all_keys = [k for k in options.defaultOptions]
        key = all_keys[0]
        default_value = str(options.defaultOptions[key][0])
        text = options.defaultOptions[key][1]
        all_values = [str(options.GetOption(key)) for key in all_keys]
        self.values = dict( [ (key, value) for (key, value) in zip(all_keys, all_values)] )                           

        self.Title = wx.StaticText(self.sp, wx.ID_ANY, '%s' % key)
        self.Title.SetFont(titleFont)
        self.Description = wx.StaticText(self.sp, -1,  '\n%s.\nDefault value = %s\n' % (text, default_value) )
        self.Input = wx.TextCtrl(self.sp, -1, all_values[0] )
        self.Bind(wx.EVT_TEXT, self.onChangeValues, self.Input)

        sz2.Add(self.Title, 0, wx.LEFT|wx.ALL, 2)
        sz2.Add(self.Description, 0, wx.LEFT|wx.ALL, 2)
        sz2.Add(self.Input, 0, wx.LEFT|wx.ALL, 2)
        sz2.Add ( (wx.StaticLine(self.sp)), 0, wx.EXPAND|wx.TOP|wx.BOTTOM, 5 )
        
        self.sp.SetSizer(sz2)
        #########

        #########
        btnSz = wx.BoxSizer(wx.HORIZONTAL)
        saveBtn = wx.Button(self, wx.ID_SAVE)
        clearBtn = wx.Button(self, wx.ID_CANCEL)
        self.Bind(wx.EVT_BUTTON, self.onCancel, clearBtn)
        self.Bind(wx.EVT_BUTTON, self.onSave, saveBtn)
        btnSz.Add (saveBtn, 0, wx.ALL, 5) 
        btnSz.Add (clearBtn, 0, wx.ALL, 5) 
        #########

        sz1.Add (self.sp, 1, wx.EXPAND|wx.ALL, 10)
        sz1.Add (btnSz, 0, wx.EXPAND, 0)
        
        mainSizer.Add(self.tb, 0, wx.EXPAND|wx.ALL,1)
        mainSizer.Add(sz1, 0, wx.EXPAND|wx.ALL,1)
        
        self.SetSizer(mainSizer)

    def onChangeValues(self, event):
        """
        """
        key = self.Title.GetLabel()
        self.values[key] = event.GetString()

    def onSelect(self, event):
        """
        """
        key = event.GetString()
        self.updatePanel(key)

    def updatePanel(self, key):
        """
        """
        default_value = str(options.defaultOptions[key][0])
        text = options.defaultOptions[key][1]
        act_value = self.values[key]
        
        self.Title.SetLabel('%s' % key)
        self.Description.SetLabel('\n%s.\nDefault value = %s' % (text, default_value))
        self.Input.SetValue(act_value)        
        
    def onCancel(self, event):
        """
        """
        self.parent.Destroy()
        
    def onSave(self, event):
        """
        """
        keys = [key for key in options.defaultOptions]
        
        for k in keys:
            v = self.values[k]
            v = v.replace('(',''); v = v.replace(')','')
            options.SetValue('Options', k, v)
        
        options.Save()
        self.parent.Close()

class optionsFrame(wx.Frame):
    def __init__(self, *args, **kwargs):
        kwargs["style"] = wx.SYSTEM_MENU | wx.CAPTION
        kwargs["size"] = (600, 400)

        wx.Frame.__init__(self, *args, **kwargs)
        opt_panel =  pvg_OptionsPanel(self)
        

if __name__ == '__main__':

    # Run as standalone
    app=wx.PySimpleApp(0)
    frame_opt = optionsFrame(None, -1, '')
    app.SetTopWindow(frame_opt)
    frame_opt.Show()
    app.MainLoop()

