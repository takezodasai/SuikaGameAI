"""Short real Tk widget tests; no Unity, sockets or game actions."""
import unittest
from suika_ai.video_viewer import ViewerLayout, fitted_size, WIDTH, HEIGHT

class ViewerLayoutTests(unittest.TestCase):
    def test_fit_preserves_aspect_and_bounds(self):
        for width,height in [(320,180),(640,360),(1900,1000),(997,573)]:
            zoom,sub=fitted_size(width,height)
            self.assertLessEqual(WIDTH*zoom/sub,width)
            self.assertLessEqual(HEIGHT*zoom/sub,height)

    def test_output_photo_reused_without_stale_pixels(self):
        import tkinter as tk
        root=tk.Tk()
        try:
            root.geometry('800x500');toolbar=tk.Frame(root);toolbar.pack();grid=tk.Frame(root);grid.pack(fill='both',expand=True)
            box=tk.Frame(grid);box.rowconfigure(0,weight=1);box.columnconfigure(0,weight=1)
            label=tk.Label(box);label.grid(sticky='nsew');tile=dict(game='game_00',box=box,label=label)
            layout=ViewerLayout(root,toolbar,grid,[tile]);root.update()
            red=tk.PhotoImage(width=WIDTH,height=HEIGHT);red.put('red',to=(0,0,WIDTH,HEIGHT))
            blue=tk.PhotoImage(width=WIDTH,height=HEIGHT);blue.put('blue',to=(0,0,WIDTH,HEIGHT))
            layout.render(tile,red);display=label.image;self.assertEqual(display.get(3,3),(255,0,0))
            layout.render(tile,blue);self.assertIs(display,label.image);self.assertEqual(display.get(3,3),(0,0,255))
        finally:root.destroy()

    def test_runtime_selection_and_fullscreen(self):
        import tkinter as tk
        root=tk.Tk()
        try:
            root.geometry("1000x700")
            toolbar=tk.Frame(root);toolbar.pack(fill="x")
            grid=tk.Frame(root);grid.pack(fill="both",expand=True)
            tiles=[]
            for i in range(4):
                box=tk.LabelFrame(grid,width=320,height=200);box.grid_propagate(False)
                box.rowconfigure(0,weight=1);box.columnconfigure(0,weight=1)
                label=tk.Label(box);label.grid(sticky="nsew")
                tiles.append(dict(game=f"game_{i:02}",box=box,label=label))
            layout=ViewerLayout(root,toolbar,grid,tiles);root.update()
            self.assertEqual(sum(t["box"].winfo_ismapped() for t in tiles),4)
            for tile in tiles:
                layout.buttons[tile["game"]].invoke();root.update()
                self.assertEqual([t["game"] for t in tiles if t["box"].winfo_ismapped()],[tile["game"]])
                self.assertGreater(tile["box"].winfo_height(),500)
                source=tk.PhotoImage(width=WIDTH,height=HEIGHT)
                layout.render(tile,source);root.update()
                self.assertLessEqual(tile["label"].image.width(),tile["label"].winfo_width())
                self.assertLessEqual(tile["label"].image.height(),tile["label"].winfo_height())
            root.focus_force();root.update()
            root.event_generate("<F11>");root.update()
            self.assertTrue(layout.fullscreen)
            self.assertTrue(root.attributes("-fullscreen"))
            root.event_generate("<Escape>");root.update()
            self.assertFalse(layout.fullscreen)
            self.assertFalse(root.attributes("-fullscreen"))
            layout.buttons[None].invoke();root.update()
            self.assertEqual(sum(t["box"].winfo_ismapped() for t in tiles),4)
            with self.assertRaises(ValueError):layout.show("game_99")
        finally:root.destroy()

if __name__=="__main__":unittest.main()
