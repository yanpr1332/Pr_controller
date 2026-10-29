from pr_controller import PremiereController
c=PremiereController()
print(c.doctor())
print(c.capabilities())
print(c.timeline())
# Explicit mutation examples (uncomment only in your test project):
# c.configure_sequence(width=1920,height=1080,fps=30)
# c.place_media('FULL/PATH/TO/VIDEO.mp4',0,source_out=5,media='both')
# print(c.shift_timeline(5,2,dry_run=True))
# c.animate(0,0,[{'component':'AE.ADBE Opacity','index':0,
#   'keys':[{'seconds':0,'value':0},{'seconds':1,'value':100}]}])
