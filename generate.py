import sys
import gzip
import argparse
import tailer

argparser = argparse.ArgumentParser(description='Parse tracelogs and create html output for them.')
argparser.add_argument('logfile', nargs='+',
                   help='the logfile to parse')
argparser.add_argument('-o', '--outfile', default="stdout",
                   help='the name of the html output file')
argparser.add_argument('-w', '--width', type=int, default=40000,
                   help='width in px (default: 40000)')
argparser.add_argument('-n', '--name', default=None,
                   help='Benchmark name')
argparser.add_argument('-r', '--revision', default=None,
                   help='Revision the shell or browser executable was built from')
args = argparser.parse_args()

logFilenames = args.logfile
outFilename = args.outfile
pixels = args.width
bench_name = args.name
revno = args.revision

max_ticks = 0
for logFilename in logFilenames:
    tail = tailer.tail(open(logFilename), 1)[0].split(",")[0]
    max_ticks = max(max_ticks, int(tail))
zoom = pixels*1./max_ticks
time = 0

start = 0
status = ""
oldline = ""

if outFilename == "stdout":
    outfile = sys.stdout
elif outFilename == "stderr":
    outfile = sys.stderr
else:
    outfile = open(outFilename, 'w')

names = {
  "n": "nothing run",
  "s": "script run",
  "s i": "interpreter run",
  "s b": "baseline run",
  "s o": "ion run",
  "c": "ion compile",
  "r": "yarr",
  "g": "minor_gc",
  "G": "gc",
  "pf": "parser_function",
  "ps": "parser_script",
  "pl": "parser_lazy",
}
engines = {
  "i": "Interpreter",
  "b": "Baseline",
  "o": "IonMonkey",
  "": ""
}


###################################################
outfile.write("<html>\n")
outfile.write("<head>\n")
outfile.write("<script src='basic.js'></script>\n")
outfile.write("<link rel='stylesheet' type='text/css' href='style.css'>\n")
outfile.write("</head>\n")
outfile.write("<body>\n")
if bench_name:
  outfile.write("<h1>"+bench_name+"</h1>\n")
if revno:
  outfile.write("<p>Revision: <a href='https://hg.mozilla.org/mozilla-central/rev/"+revno+"'>"+revno+"</a></p>\n")

outfile.write("<div id=legend>\n")
outfile.write("<p><span class='block interpreter run'></span> interpreter</p>\n")
outfile.write("<p><span class='block ion compile'></span> ionmonkey compilation</p>\n")
outfile.write("<p><span class='block ion run'></span> ionmonkey running</p>\n")
outfile.write("<p><span class='block jm run'></span> baseline running</p>\n")
outfile.write("<p><span class='block yarr jit'></span> yarr jit</p>\n")
outfile.write("<p><span class='block gc'></span> GC</p>\n")
outfile.write("<p><span class='block minor_gc'></span> Minor GC</p>\n")
outfile.write("<p><span class='block parser_script'></span> Script parsing</p>\n")
outfile.write("<p><span class='block parser_lazy'></span> Lazy parsing</p>\n")
outfile.write("<p><span class='block parser_function'></span> Function parsing</p>\n")
outfile.write("<!--<div><p>1px = "+str(int(1./zoom))+" kernel ticks</p></div>-->\n")
outfile.write("</div>\n")
outfile.write("<div class='graph'>\n")

def create_backtrace(stack):
    full_info = ""
    for entry in stack:
        full_info += "; -"+",".join(entry["data"][2:])
        if "engine" in entry:
            full_info += " " + engines[entry["engine"]]
    return full_info

block_time = 0
block_width = 10
aggregate = 0
def output(delta, stacks):
    global text, block_time, aggregate

    width = delta * zoom + aggregate

    # Don't show entries that are too small.
    if width < 1:
      aggregate = width
      return

    aggregate = 0

    block = ""
    for i in range(len(stacks)):
        stack = stacks[i]
        info = stack[-1]

        class_ = info["data"][2]
        engine = ""
        if "engine" in info:
            engine = info["engine"]
            class_ += " " + engine

        full_info = create_backtrace(stack)
        block += "<span class='block "+names[class_]+"' info='Thread: "+str(i)+";Block: "+str(block_time)+";Engine: "+engines[engine]+";<b>Call stack:</b>"+full_info+"'>\n</span>\n"

    # Output the current entry:
    outfile.write("<span style='width:"+str(width%block_width)+"px;' class='container'>"+block+"</span>")
    for i in range(int(width/block_width)):
      outfile.write("<span style='width:"+str(block_width)+"px' class='container'>"+block+"</span>")

    block_time += 1

from collections import defaultdict
engine_stat = defaultdict(int)
script_stat = defaultdict(lambda : defaultdict(int))
script_called = defaultdict(lambda : defaultdict(int))
text_dict = {}
next_text_id = 1

def keep_stat(delta, info):
  data = info["data"]
  engine = ""
  task = data[2]
  statkey = task
  if "engine" in info:
      engine = info["engine"]
      statkey += " " + engine
  if engine != "" or task != "s":
      engine_stat[statkey] += delta

  # Any script running (if engine is set) / ion compiling / any parsing
  if (task == "s" and engine != "") or task == "c" or task[0] == "p":
      script = data[3]
      script_stat[script][statkey] += delta

def keep_stat_start(info):
  global next_text_id
  data = info["data"]
  task = data[2]
  # Any script running / ion compiling / any parsing
  if task == "s" or task == "c" or task[0] == "p":
      text_id = data[3]
      if not text_id.isdigit():
          text = text_id
          text_id = str(next_text_id)
          next_text_id += 1
          text_dict[text_id] = text
      else:
          if text_id in text_dict:
              text = text_dict[text_id]
          else:
              text = "Unrecoverable text"
      number = data[4]
      script = data[3] = text + ":" + number
      script_called[script][task] += 1

##################################################""

class LogReader:

    def __init__(self, name):
        self.stack_ = [{"data":["0","1","n"]}]
        self.time = 0
        self.current_ = None
        self.next_ = None
        self.done_ = False

        if ".gz" in name:
            self.fp = gzip.open(name)
        else:
            self.fp = open(name)

        self.next()

    def increase(self, time):
        changed = False
        while time >= self.duration:
            time -= self.duration
            self.next()
            changed = True

        self.duration -= time
        return changed

    def next(self):
        while True:
            try:
                line = self.fp.next()
                next_ = line[:-1].split(",")
            except StopIteration:
                self.done_ = True
                return
            
            # Only process data with timestamp,event 
            if len(next_) < 2:
                continue

            # Only process data for start/stop or engine change.
            if next_[1] not in ["1","0","e"]:
                continue

            self.current_ = self.next_
            self.next_ = next_

            if self.current_ == None:
                self.duration = int(self.next_[0])
                return

            self.duration = int(self.next_[0]) - int(self.current_[0])

            if self.isStart():
                self.stack_.append({"data": self.current_})
                # Hack to remove unreported engine between starting a script
                # and logging engine that is running
                if self.next_[1] == "e" and self.current_[2] == "s":
                    self.stack_[-1]["engine"] = self.next_[2][0]

            else:
                if self.isEngineChange():
                    self.stack_[-1]["engine"] = self.current_[2][0]
                else:
                    assert self.isStop()
                    self.stack_ = self.stack_[:-1]
            return

    def isStart(self):
        return self.current_[1] == "1"
    def isStop(self):
        return self.current_[1] == "0"
    def isEngineChange(self):
        return self.current_[1] == "e"
    def info(self):
        return self.stack_[-1]
    def isDone(self):
        return self.done_
    def stack(self):
        return self.stack_

readers = []
for logFilename in logFilenames:
    readers.append(LogReader(logFilename))

tick = 0
while tick < max_ticks:
    min_duration = max_ticks
    for reader in readers:
        if reader.isDone():
            continue
        if reader.duration < min_duration:
            min_duration = reader.duration

    tick += min_duration 
    output_stack = []
    for reader in readers:
        if reader.isDone():
            output_stack.append([{"data":["0","1","n"]}])
            continue
        has_new_data = reader.increase(min_duration)
        output_stack.append(reader.stack())
        
        if not has_new_data:
            continue
        # Only keep stats of first reader for now.
        if readers[0] != reader:
            continue

        if reader.isStart():
            keep_stat_start(reader.info())
        keep_stat(reader.duration, reader.info())

    output(min_duration, output_stack)


##########################################################
outfile.write("</div>\n")

total = 0
total_script = 0
for i in engine_stat:
  total += engine_stat[i]
  # Any script running / ion compiling / any parsing
  if i[0] == "s" or i[0] == "c" or i[0] == "p":
    total_script += engine_stat[i]

outfile.write("<h2>Engine overview</h2>\n")
outfile.write("<table>\n")
outfile.write("<thead><td>Engine</td><td>Percent</td></thead>\n")
for i in engine_stat:
  outfile.write("<tr><td>"+str(names[i])+"</td><td>%.2f%%</td></tr>\n" % (engine_stat[i]*100./total))
outfile.write("</table>\n")

outfile.write("<h2>Script overview</h2>\n")
outfile.write("<table>\n")
outfile.write("<thead><td>Script</td><td>Times called</td><td>Times compiled</td><td>Total time</td><td>Time spent</td></thead>\n")
for script_location in script_stat:
  script = script_stat[script_location]
  total = 0
  for j in script:
    total += script[j]

  outfile.write("<tr><td>" + script_location + "</td>\n")
  outfile.write("<td>"+str(script_called[script_location]["s"])+"</td>\n")
  outfile.write("<td>"+str(script_called[script_location]["c"])+"</td>\n")
  outfile.write("<td>%.2f%%</td><td>\n" % (total*100./total_script))
  for j in script:
    outfile.write(names[j]+": %.2f%%, \n" % (script[j]*100./total))
  outfile.write("</td></tr>\n")
outfile.write("</table>\n")

outfile.write("</body>\n")
outfile.write("</html>\n")
