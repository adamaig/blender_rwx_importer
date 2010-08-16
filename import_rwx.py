#!BPY
 
"""
Name: 'Renderware (.rwx)...'
Blender: 249
Group: 'Import'
Tooltip: 'Load an ActiveWorlds RWX File, Shift: batch import all dir.'
"""

__author__= "Adam Ingram-Goble"
__url__= ['adamaig.wordpress.com']
__version__= "0.1"

__bpydoc__= """\
This script imports a Renderware/Activeworlds RWX files to Blender.

Usage:
Run this script from "File->Import" menu and then load the desired RWX file.
Note, This loads mesh objects and materials only, nurbs and curves are not supported.
"""

# ***** BEGIN LICENSE BLOCK *****
#
# Script copyright (C) Adam Ingram-Goble
#
# ***** END LICENCE BLOCK *****
# --------------------------------------------------------------------------

import Blender
from Blender import Mesh, Draw, Window, Texture, Material, Mathutils, sys
import bpy
import BPyMesh
import BPyImage
import BPyMessages
import re, traceback, sys

try:    import os
except:   os= False

## GLOBALS ##
scene = bpy.data.scenes.active # link object to current scene
prototypes = {}  # proto definitions will be added here, with keys based on names
proto_layer = 2 # put all proto geometrys here

# because transform matrices are fun
transform_stack = []  
joint_transform_stack = []
materials_stack = []
transform_stack.append(Blender.Mathutils.Matrix()) # start with the identity matrix
joint_transform_stack.append(Blender.Mathutils.Matrix()) # start with the identity matrix
materials_stack.append(make_default_material(Blender.Material.New()))

# Regexps for RWX commands
re_vertex   = re.compile('^\s*vertex ((-?\d*(.\d+)?\s*){3})\s*(uv\s+((-?\d*(.\d+)?\s*?){2}))?', re.I)
re_triangle = re.compile('^\s*triangle', re.I)
re_polygon  = re.compile('^\s*polygon', re.I)
re_quad     = re.compile('^\s*quad', re.I)

# Primitives
re_block    = re.compile('^\s*block', re.I)
re_cone     = re.compile('^\s*cone', re.I)
re_cylinder = re.compile('^\s*cylinder', re.I)
re_disc     = re.compile('^\s*disc', re.I)
re_sphere   = re.compile('^\s*sphere', re.I)

# Transformation commands
re_identity  = re.compile('^\s*identity\s*$', re.I)
re_transform = re.compile('^\s*transform\s', re.I)
re_translate = re.compile('^\s*translate', re.I)
re_rotate    = re.compile('^\s*rotate', re.I)
re_scale     = re.compile('^\s*scale', re.I)
re_transformbegin = re.compile('^\s*transformbegin', re.I)
re_transformend   = re.compile('^\s*transformend', re.I)

re_joint_identity  = re.compile('^\s*identityjoint', re.I)
re_joint_transform = re.compile('^\s*transformjoint\s', re.I)
re_joint_rotate    = re.compile('^\s*rotatejoint', re.I)
re_joint_transformbegin = re.compile('^\s*jointtransformbegin', re.I)
re_joint_transformend   = re.compile('^\s*jointtransformend', re.I)

# RWX material commands
re_color    = re.compile('^\s*color', re.I)
re_surface  = re.compile('^\s*surface', re.I)
re_opacity  = re.compile('^\s*opacity', re.I)
re_light_sampling = re.compile('^\s*lightsampling', re.I)

# structural RWX commands
re_modelbegin = re.compile('^\s*modelbegin', re.I)
re_modelend   = re.compile('^\s*modelend', re.I)
re_protobegin = re.compile('^\s*protobegin', re.I)
re_protoend   = re.compile('^\s*protoend', re.I)
re_clumpbegin = re.compile('^\s*clumpbegin', re.I)
re_clumpend   = re.compile('^\s*clumpend', re.I)

re_protoinstance = re.compile('^\s*protoinstance', re.I)

# Generic path functions
def stripFile(path):
  '''Return directory, where the file is'''
  lastSlash= max(path.rfind('\\'), path.rfind('/'))
  if lastSlash != -1:
    path= path[:lastSlash]
  return '%s%s' % (path, sys.sep)

def stripPath(path):
  '''Strips the slashes from the back of a string'''
  return path.split('/')[-1].split('\\')[-1]

def stripExt(name): # name is a string
  '''Strips the prefix off the name before writing'''
  index= name.rfind('.')
  if index != -1:
    return name[ : index ]
  else:
    return name
# end path funcs


# materials management functions
def make_default_material():
  """Renderware defaults:
  
  Ambient  CREAL(0.0)
  Diffuse  CREAL(0.0)
  Specular CREAL(0.0)
  Light Sampling  rwFACET
  Geometry Sampling  rwSOLID
  Color  [CREAL(0.0), CREAL(0.0), CREAL(0.0)] (Black)
  Opacity  CREAL(1.0)
  Texture  NULL
  Texture Modes  rwLIT
  """
  mat = Blender.Material.New()
  mat.setAmb(0.0)
  mat.setRef(0.0) # treating blender's reflectivity as RWX's diffuse setting
  mat.setSpec(0.0)
  mat.setAlpha(0.0)
  mat.setRGBCol(None)
  
def set_face_colors(face,colors):
  '''
  Sets the vertex colors for the face
  '''
  for i, v in enumerate(face):
    col = face.col[i]
    col.r = int(255 * (v.no.x+1) * colors[0])
    col.g = int(255 * (v.no.y+1) * colors[1])
    col.b = int(255 * (v.no.z+1) * colors[2])

def add_face(target_mesh, vertex_list, colors):
  """
  add_face adds a face to the specified mesh
  """
  face_list = target_mesh.faces.extend( vertex_list, indexList=True)
  if(face_list[0] is not None):
    for f in target_mesh.faces[face_list[0]]: f.uv = tuple([ v.uvco for v in f])
    set_face_colors( target_mesh.faces[face_list[0]], colors)

def append_mesh(m1,m2):
  """Adds mesh m2 to m1"""
  
  # trick because if you use m2.verts[:] you just get PVerts, not MVerts ... wtf
  m2_verts = [m for m in m2.verts] 
  
  m1_size = len(m1.verts[:])
  v_copies = [ x.co for x in m2_verts ] # doesn't handle uv coordinates
  f_copies = [ [x.index + m1_size for x in y.verts] for y in m2.faces]
  m1.verts.extend(v_copies)
  m1.faces.extend(f_copies)
  # now setup the vertex uv coords, this will make setting up face uvs easy later
  if m2.vertexUV:
    for v in m2_verts:
      if v.uvco:
        m1.verts[m1_size + v.index].uvco = v.uvco
  
  # copy colors
  
  #
  # recalculate normals
  m1.recalcNormals()
  m1.calcNormals()

def get_children(obj):
  """finds the children of the current target"""
  return [ x for x in bpy.data.objects if x.parent == obj]

def copy_object_children(dup, obj):
  """docstring for copy_object_clump"""
  for child in get_children(obj):
    dup_m = bpy.data.meshes.new("im_"+child.getData(name_only=1))
    dup_o = scene.objects.new(dup_m, 'iob_' + child.getData(name_only=1))
    dup_o.setMatrix(dup.matrix * child.matrix)
    dup_m.getFromObject(child)
    copy_object_children(dup_o, child)
    dup.makeParent([dup_o])

def command_not_implemented(command_line):
  """
  command_not_implemented outputs commands that are not processed
  """
  print "*** Skipping Command: '%s'" % command_line

def clear_out_protos():
  """Deletes all objects in layer 2 where the protos are stuck during import"""
  protos = [obj for obj in bpy.data.objects if proto_layer in set(obj.layers)]
  for proto in protos: 
    scene.unlink(proto)
    
def load_rwx(filepath):
  '''
  Called by the user interface or another script.
  load_rwx(path) - should give acceptable results.
  This function passes the file and sends the data off
    to be split into objects and then converted into mesh objects
  '''
  
  global prototypes, scene
  
  print '\nimporting rwx "%s"' % filepath
  
  time_main= Blender.sys.time()  
  colors = [1,1,1] # colors, r,g,b
  
  editmode = Window.EditMode()    # are we in edit mode?  If so ...
  if editmode: Window.EditMode(0) # leave edit mode before getting the mesh

  mesh_name = stripPath(filepath)
  
  # The first several commands here are for structuring the object heirarchy
  # The general approach here is to create a new object for each mesh 
  # instantiation. Because a model may contain multiple parallel clumps at
  # the top level, we create an empty object at the top level
  top_mesh = bpy.data.meshes.new(mesh_name) # the top level mesh
  top_object = scene.objects.new(top_mesh, mesh_name)
  scene.objects.active = top_object
  scene.setName(mesh_name)
  
  print '\tparsing rwx file "%s"...' % filepath
  time_sub = Blender.sys.time()
  
  aw_file = open(filepath, 'rU') # the file object to read from
  
  current_mesh = top_mesh
  current_object = top_object
  proto_context = None
  line_no = 0
  in_proto = False
  
  for line in aw_file: 
    line_no += 1
    line = line.lstrip().rstrip() # rare cases there is white space at the start of the line
    line_split = line.split()
    
    try:
      if len(line) == 0:
        pass
        
      elif   re_modelbegin.search(line):
        current_mesh = top_mesh
        
      elif re_modelend.search(line):
        pass
        
      elif re_protobegin.search(line):
        # store the context that the proto is created within
        proto_context = { 'object' : current_object, 'mesh' : current_mesh }
        in_proto = True
        
        proto_name = line.split()[1]
        current_mesh = bpy.data.meshes.new("p_"+proto_name)
        current_mesh.vertexUV = current_mesh.vertexColors = True
        
        current_object = scene.objects.new(current_mesh, 'pob' + proto_name)
        prototypes[proto_name] = current_object
        current_object.layers = [proto_layer]

      elif re_protoend.search(line):
        # restore the pre-proto context
        current_mesh, current_object = proto_context['mesh'], proto_context['object']
        in_proto = False

      elif re_clumpbegin.search(line):
        sub_mesh = bpy.data.meshes.new('m_line_%s' % line_no)
        current_mesh = sub_mesh
        current_mesh.vertexUV = current_mesh.vertexColors = True
        
        sub_object = scene.objects.new(sub_mesh, 'ob_%s' % line_no)
        current_object.makeParent([sub_object])
        current_object = sub_object
        if in_proto: current_object.layers = [proto_layer]
        
        current_object.setMatrix(transform_stack[-1]*current_object.matrix)
        # push the default of the top of the stack of transforms and materials
        transform_stack.append(Mathutils.Matrix())
        joint_transform_stack.append(Mathutils.Matrix())
        # materials_stack.append(materials_stack[-1].copy()) # start with a copy matrix
        
      elif re_clumpend.search(line):
        current_object = current_object.getParent()
        current_mesh = current_object.getData(mesh=True)
        # pop the top of the stack of transforms and materials
        transform_stack.pop()
        joint_transform_stack.pop()
        # materials_stack.pop()
      
      elif re_protoinstance.search(line):
        proto_name = line_split[1]
        # add any possible child clump definitions to the object.
        # meshes in the top level just get added directly to the current mesh
        copy_object_children(current_object, prototypes[proto_name])
        mesh_copy = prototypes[proto_name].getData(mesh=True).__copy__()
        mesh_copy.transform(transform_stack[-1], recalc_normals=True)
        append_mesh(current_mesh, mesh_copy)
        
      elif re_vertex.search(line):
        current_mesh.verts.extend( [[float(line_split[1]), float(line_split[2]), float(line_split[3])]] )
        v = current_mesh.verts[-1]
        if len(line_split) > 4 and (line_split[4] == 'UV' or line_split[4] == 'uv'):
          v.uvco = (float(line_split[5]), float(line_split[6]))
        else:
          v.uvco = (0.5, 0.5)
          
      elif re_triangle.search(line):
        add_face( current_mesh, [[int(line_split[1])-1, int(line_split[2])-1, int(line_split[3])-1]], colors)
        
      elif re_quad.search(line):
        add_face( current_mesh, [[int(line_split[1])-1, int(line_split[2])-1, int(line_split[3])-1, int(line_split[4])-1]], colors)
      
      elif re_polygon.search(line): # carves the polygon up into triangles
        for i in range(2,len(line_split)-1): 
          add_face( current_mesh,[[int(line_split[2])-1, int(line_split[i])-1, int(line_split[i+1])-1]], colors)
      
      elif re_block.search(line):
        block_mesh = Mesh.Primitives.Cube(2) # makes scaling it easy
        size_x, size_y, size_z = map(float, line_split[1:])
        mat_sc = 0.5 * Mathutils.Matrix([size_x,0,0,0], [0,size_y,0,0],[0,0,size_z,0], [0,0,0,1])
        block_mesh.transform(mat_sc)
        block_mesh.transform(transform_stack[-1], recalc_normals=True)
        append_mesh(current_mesh, block_mesh)
        
      # Transform commands
      elif re_identity.search(line):
        transform_stack[-1].identity()
        
      elif re_transformbegin.search(line):
        transform_stack.append(transform_stack[-1].copy()) # start with a copy matrix
      
      elif re_transformend.search(line):
        transform_stack.pop()
        
      elif re_translate.search(line):
        x, y, z = map(float, line_split[1:4])
        mat_trans = Mathutils.TranslationMatrix(Blender.Mathutils.Vector(x,y,z))
        transform_stack[-1] = mat_trans * transform_stack[-1]
        
      elif re_rotate.search(line):
        x, y, z, d = map(float, line_split[1:5])
        mat_rot = Mathutils.RotationMatrix(d,4,"r",Mathutils.Vector(x,y,z))
        transform_stack[-1] = mat_rot * transform_stack[-1]
      
      elif re_scale.search(line):
        x, y, z = map(float, line_split[1:4])
        mat_sca = Mathutils.Matrix([x,0,0,0], [0,y,0,0],[0,0,z,0], [0,0,0,1])
        transform_stack[-1] = mat_sca * transform_stack[-1]
        
      elif re_transform.search(line):
        m11, m21, m31, m41, m12, m22, m32, m42, m13, m23, m33, m43, m14, m24, m34, m44 = map(float, line_split[1:])
        # Notice we over-ride certain values here. This is because they get ignored by RWX.
        mat_tx = Mathutils.Matrix([m11, m21, m31, 0], [m12, m22, m32, 0], [m13, m23, m33, 0], [m14, m24, m34, 1])
        transform_stack[-1] = mat_tx
      
      elif re_color.search(line):
        colors = [float(line_split[1]), float(line_split[2]), float(line_split[3])]
        materials_stack[-1].setRGBCol(colors)
        
      elif re_surface.search(line):
        pass
      elif re_opacity.search(line):
        pass
      elif re_light_sampling.search(line):
        pass
      else: 
        command_not_implemented(line)
        
    except Exception, e:
      print '*** Encountered an error processing "%s"' %  line
      exc_type, exc_value, exc_traceback = sys.exc_info()
      traceback.print_exception(exc_type, exc_value, exc_traceback, limit=None, file=sys.stdout)
      # raise e
  
  aw_file.close()
  
  if editmode: Window.EditMode(1)  # optional, just being nice       
  
  # unfuck the orientation, because why rotate x, and invert y ?
  mat_tx = Mathutils.RotationMatrix(-180,4,"y") * Mathutils.RotationMatrix(90,4,"x")
  top_object.setMatrix( mat_tx * top_object.matrix)
  clear_out_protos()
  Window.RedrawAll()
  
  time_new= Blender.sys.time()
  print '%.4f sec' % (time_new-time_sub)
  print 'finished importing: "%s" in %.4f sec.' % (filepath, (time_new-time_main))

def load_obj_ui(filepath, BATCH_LOAD= False):
  if BPyMessages.Error_NoFile(filepath):
    return
  
  global CREATE_SMOOTH_GROUPS, CREATE_FGONS, CREATE_EDGES, SPLIT_OBJECTS, SPLIT_GROUPS, SPLIT_MATERIALS, CLAMP_SIZE, IMAGE_SEARCH, POLYGROUPS, KEEP_VERT_ORDER, ROTATE_X90
  
  CREATE_SMOOTH_GROUPS= Draw.Create(0)
  CREATE_FGONS= Draw.Create(1)
  CREATE_EDGES= Draw.Create(1)
  SPLIT_OBJECTS= Draw.Create(0)
  SPLIT_GROUPS= Draw.Create(0)
  SPLIT_MATERIALS= Draw.Create(0)
  CLAMP_SIZE= Draw.Create(10.0)
  IMAGE_SEARCH= Draw.Create(1)
  POLYGROUPS= Draw.Create(0)
  KEEP_VERT_ORDER= Draw.Create(1)
  ROTATE_X90= Draw.Create(1)
  
  
  # Get USER Options
  # Note, Works but not pretty, instead use a more complicated GUI
  '''
  pup_block= [\
  'Import...',\
  ('Smooth Groups', CREATE_SMOOTH_GROUPS, 'Surround smooth groups by sharp edges'),\
  ('Create FGons', CREATE_FGONS, 'Import faces with more then 4 verts as fgons.'),\
  ('Lines', CREATE_EDGES, 'Import lines and faces with 2 verts as edges'),\
  'Separate objects from obj...',\
  ('Object', SPLIT_OBJECTS, 'Import OBJ Objects into Blender Objects'),\
  ('Group', SPLIT_GROUPS, 'Import OBJ Groups into Blender Objects'),\
  ('Material', SPLIT_MATERIALS, 'Import each material into a seperate mesh (Avoids > 16 per mesh error)'),\
  'Options...',\
  ('Keep Vert Order', KEEP_VERT_ORDER, 'Keep vert and face order, disables some other options.'),\
  ('Clamp Scale:', CLAMP_SIZE, 0.0, 1000.0, 'Clamp the size to this maximum (Zero to Disable)'),\
  ('Image Search', IMAGE_SEARCH, 'Search subdirs for any assosiated images (Warning, may be slow)'),\
  ]
  
  if not Draw.PupBlock('Import OBJ...', pup_block):
    return
  
  if KEEP_VERT_ORDER.val:
    SPLIT_OBJECTS.val = False
    SPLIT_GROUPS.val = False
    SPLIT_MATERIALS.val = False
  '''
  
  
  
  # BEGIN ALTERNATIVE UI *******************
  if True: 
    
    EVENT_NONE = 0
    EVENT_EXIT = 1
    EVENT_REDRAW = 2
    EVENT_IMPORT = 3
    
    GLOBALS = {}
    GLOBALS['EVENT'] = EVENT_REDRAW
    #GLOBALS['MOUSE'] = Window.GetMouseCoords()
    GLOBALS['MOUSE'] = [i/2 for i in Window.GetScreenSize()]
    
    def obj_ui_set_event(e,v):
      GLOBALS['EVENT'] = e
    
    def do_split(e,v):
      global SPLIT_OBJECTS, SPLIT_GROUPS, SPLIT_MATERIALS, KEEP_VERT_ORDER, POLYGROUPS
      if SPLIT_OBJECTS.val or SPLIT_GROUPS.val or SPLIT_MATERIALS.val:
        KEEP_VERT_ORDER.val = 0
        POLYGROUPS.val = 0
      else:
        KEEP_VERT_ORDER.val = 1
      
    def do_vertorder(e,v):
      global SPLIT_OBJECTS, SPLIT_GROUPS, SPLIT_MATERIALS, KEEP_VERT_ORDER
      if KEEP_VERT_ORDER.val:
        SPLIT_OBJECTS.val = SPLIT_GROUPS.val = SPLIT_MATERIALS.val = 0
      else:
        if not (SPLIT_OBJECTS.val or SPLIT_GROUPS.val or SPLIT_MATERIALS.val):
          KEEP_VERT_ORDER.val = 1
      
    def do_polygroups(e,v):
      global SPLIT_OBJECTS, SPLIT_GROUPS, SPLIT_MATERIALS, KEEP_VERT_ORDER, POLYGROUPS
      if POLYGROUPS.val:
        SPLIT_OBJECTS.val = SPLIT_GROUPS.val = SPLIT_MATERIALS.val = 0
      
    def do_help(e,v):
      url = __url__[0]
      print 'Trying to open web browser with documentation at this address...'
      print '\t' + url
      
      try:
        import webbrowser
        webbrowser.open(url)
      except:
        print '...could not open a browser window.'
    
    def obj_ui():
      ui_x, ui_y = GLOBALS['MOUSE']
      
      # Center based on overall pup size
      ui_x -= 165
      ui_y -= 90
      
      global CREATE_SMOOTH_GROUPS, CREATE_FGONS, CREATE_EDGES, SPLIT_OBJECTS, SPLIT_GROUPS, SPLIT_MATERIALS, CLAMP_SIZE, IMAGE_SEARCH, POLYGROUPS, KEEP_VERT_ORDER, ROTATE_X90
      
      Draw.Label('Import...', ui_x+9, ui_y+159, 220, 21)
      Draw.BeginAlign()
      Draw.PushButton('Online Help', EVENT_REDRAW, ui_x+9, ui_y+9, 110, 21, 'Load the wiki page for this script', do_help)
      Draw.PushButton('Cancel', EVENT_EXIT, ui_x+119, ui_y+9, 110, 21, '', obj_ui_set_event)
      Draw.PushButton('Import', EVENT_IMPORT, ui_x+229, ui_y+9, 110, 21, 'Import with these settings', obj_ui_set_event)
      Draw.EndAlign()
      
    
    # hack so the toggle buttons redraw. this is not nice at all
    while GLOBALS['EVENT'] not in (EVENT_EXIT, EVENT_IMPORT):
      Draw.UIBlock(obj_ui, 0)
    
    if GLOBALS['EVENT'] != EVENT_IMPORT:
      return
  
  Window.WaitCursor(1)
  
  if BATCH_LOAD: # load the dir
    try:
      files= [ f for f in os.listdir(filepath) if f.lower().endswith('.obj') ]
    except:
      Window.WaitCursor(0)
      Draw.PupMenu('Error%t|Could not open path ' + filepath)
      return
    
    if not files:
      Window.WaitCursor(0)
      Draw.PupMenu('Error%t|No files at path ' + filepath)
      return
    
    for f in files:
      scn= bpy.data.scenes.new( stripExt(f) )
      scn.makeCurrent()
      
      load_rwx(sys.join(filepath, f))
  
  else: # Normal load
    load_rwx(filepath)
  
  Window.WaitCursor(0)


def load_obj_ui_batch(file):
  load_obj_ui(file, True)

if __name__=='__main__':
  if os and Window.GetKeyQualifiers() & Window.Qual.SHIFT:
    Window.FileSelector(load_obj_ui_batch, 'Import RWX Dir', '')
  else:
    Window.FileSelector(load_obj_ui, 'Import a ActiveWorlds RWX', '*.rwx')
