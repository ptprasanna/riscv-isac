# See LICENSE.incore for details
# See LICENSE.iitm for details

import ruamel
from ruamel.yaml import YAML
import riscv_isac.utils as utils
from riscv_isac.constants import *
from riscv_isac.log import logger
from collections import Counter
import sys
from riscv_isac.utils import yaml
from riscv_isac.cgf_normalize import *
import riscv_isac.fp_dataset as fmt
import struct
import pytablewriter
import importlib
import pluggy
import riscv_isac.plugins as plugins
from riscv_isac.plugins.specification import *
import math
import multiprocessing as mp
from collections.abc import MutableMapping


unsgn_rs1 = ['sw','sd','sh','sb','ld','lw','lwu','lh','lhu','lb', 'lbu', 'flh', 'flw','fld', 'fsh', 'fsw','fsd',\
        'bgeu', 'bltu', 'sltiu', 'sltu','c.lw','c.ld','c.lwsp','c.ldsp',\
        'c.sw','c.sd','c.swsp','c.sdsp','mulhu','divu','remu','divuw',\
        'remuw','aes64ds','aes64dsm','aes64es','aes64esm','aes64ks2',\
        'sha256sum0','sha256sum1','sha256sig0','sha256sig1','sha512sig0',\
        'sha512sum1r','sha512sum0r','sha512sig1l','sha512sig0l','sha512sig1h','sha512sig0h',\
        'sha512sig1','sha512sum0','sha512sum1','sm3p0','sm3p1','aes64im',\
        'sm4ed','sm4ks','ror','rol','rori','rorw','rolw','roriw','clmul','clmulh','clmulr',\
        'andn','orn','xnor','pack','packh','packu','packuw','packw',\
        'xperm.n','xperm.b','grevi','aes64ks1i', 'shfli', 'unshfli', \
        'aes32esmi', 'aes32esi', 'aes32dsmi', 'aes32dsi','bclr','bext','binv',\
        'bset','zext.h','sext.h','sext.b','minu','maxu','orc.b','add.uw','sh1add.uw',\
        'sh2add.uw','sh3add.uw','slli.uw','clz','clzw','ctz','ctzw','cpop','cpopw','rev8',\
        'bclri','bexti','binvi','bseti']
unsgn_rs2 = ['bgeu', 'bltu', 'sltiu', 'sltu', 'sll', 'srl', 'sra','mulhu',\
        'mulhsu','divu','remu','divuw','remuw','aes64ds','aes64dsm','aes64es',\
        'aes64esm','aes64ks2','sm4ed','sm4ks','ror','rol','rorw','rolw','clmul',\
        'clmulh','clmulr','andn','orn','xnor','pack','packh','packu','packuw','packw',\
        'xperm.n','xperm.b', 'aes32esmi', 'aes32esi', 'aes32dsmi', 'aes32dsi',\
        'sha512sum1r','sha512sum0r','sha512sig1l','sha512sig1h','sha512sig0l','sha512sig0h','fsw',\
        'bclr','bext','binv','bset','minu','maxu','add.uw','sh1add.uw','sh2add.uw','sh3add.uw']

class cross():

    def __init__(self,label,coverpoint):

        self.label = label
        self.coverpoint = coverpoint
        self.result = 0

        ## Extract relevant information from coverpt
        self.data = self.coverpoint.split('::')
        self.ops = [i for i in self.data[0][1:-1].split(':')]
        self.assign_lst = [i for i in self.data[1][1:-1].split(':')]
        self.cond_lst = [i for i in self.data[2][1:-1].split(':')]

    def process(self, queue, window_size, addr_pairs):

        '''
        Check whether the coverpoint is a hit or not and update the metric
        '''
        if(len(self.ops)>window_size or len(self.ops)>len(queue)):
            return

        for index in range(len(self.ops)):
            instr = queue[index]
            instr_name = instr.instr_name
            if addr_pairs:
                if not (any([instr.instr_addr >= saddr and instr.instr_addr < eaddr for saddr,eaddr in addr_pairs])):
                    continue

            rd = None
            rs1 = None
            rs2 = None
            rs3 = None
            imm = None
            zimm = None
            csr = None
            shamt = None
            succ = None
            pred = None
            rl = None
            aq = None
            rm = None

            if instr.rd is not None:
                rd = int(instr.rd[0])
            if instr.rs1 is not None:
                rs1 = int(instr.rs1[0])
            if instr.rs2 is not None:
                rs2 = int(instr.rs2[0])
            if instr.rs3 is not None:
                rs3 = int(instr.rs3[0])
            if instr.imm is not None:
                imm = int(instr.imm)
            if instr.zimm is not None:
                zimm = int(instr.zimm)
            if instr.csr is not None:
                csr = instr.csr
            if instr.shamt is not None:
                shamt = int(instr.shamt)
            if instr.succ is not None:
                succ = int(instr.succ)
            if instr.pred is not None:
                pred = int(instr.pred)
            if instr.rl is not None:
                rl = int(instr.rl)
            if instr.aq is not None:
                aq = int(instr.aq)
            if instr.rm is not None:
                rm = int(instr.rm)
            if(self.ops[index] != '?'):
                check_lst = [i for i in self.ops[index][1:-1].split(',')]
                if (instr_name not in check_lst):
                    break
            if (self.cond_lst[index] != '?'):
                if(eval(self.cond_lst[index])):
                    if(index==len(self.ops)-1):
                        self.result = self.result + 1
                else:
                    break
            if(self.assign_lst[index] != '?'):
                exec(self.assign_lst[index])

    def get_metric(self):
        return self.result


class csr_registers(MutableMapping):
    '''
    Defines the architectural state of CSR Register file.
    '''

    def __init__ (self, xlen):
        '''
        Class constructor

        :param xlen: max XLEN value of the RISC-V device

        :type xlen: int

        Currently defines the CSR register files the
        width of which is defined by the xlen parameter. These are
        implemented as an array holding the hexadecimal representations of the
        values as string. These can be accessed by both integer addresses as well as string names

        '''

        if(xlen==32):
            self.csr = ['00000000']*4096
            self.csr[int('301',16)] = '40000000' # misa
        else:
            self.csr = ['0000000000000000']*4096
            self.csr[int('301',16)] = '8000000000000000' # misa

        # M-Mode CSRs
        self.csr[int('F11',16)] = '00000000' # mvendorid
        self.csr[int('306',16)] = '00000000' # mcounteren
        self.csr[int('B00',16)] = '0000000000000000' # mcycle
        self.csr[int('B02',16)] = '0000000000000000' # minstret
        for i in range(29): # mphcounter 3-31, 3h-31h
            self.csr[int('B03',16)+i] = '0000000000000000'
            self.csr[int('B83',16)+i] = '00000000'
        self.csr[int('320',16)] = '00000000' # mcounterinhibit
        self.csr[int('B80',16)] = '00000000' # mcycleh
        self.csr[int('B82',16)] = '00000000' # minstreth

        self.csr[int('001',16)] = '00000000'
        self.csr[int('002',16)] = '00000000'
        self.csr[int('003',16)] = '00000000'

        ## mtime, mtimecmp => 64 bits, platform defined memory mapping

        # S-Mode CSRs
        self.csr[int('106',16)] = '00000000' # scounteren

        self.csr_regs={
            "mvendorid":int('F11',16),
            "marchid":int('F12',16),
            "mimpid":int('F13',16),
            "mhartid":int('F14',16),
            "mstatus":int('300',16),
            "misa":int('301',16),
            "medeleg":int('302',16),
            "mideleg":int('303',16),
            "mie":int('304',16),
            "mtvec":int('305',16),
            "mcounteren":int('306',16),
            "mscratch":int('340',16),
            "mepc":int('341',16),
            "mcause":int('342',16),
            "mtval":int('343',16),
            "mip":int('344',16),
            "pmpcfg0":int('3A0',16),
            "pmpcfg1":int('3A1',16),
            "pmpcfg2":int('3A2',16),
            "pmpcfg3":int('3A3',16),
            "mcycle":int('B00',16),
            "minstret":int('B02',16),
            "mcycleh":int('B80',16),
            "minstreth":int('B82',16),
            "mcountinhibit":int('320',16),
            "tselect":int('7A0',16),
            "tdata1":int('7A1',16),
            "tdata2":int('7A2',16),
            "tdata3":int('7A3',16),
            "dcsr":int('7B0',16),
            "dpc":int('7B1',16),
            "dscratch0":int('7B2',16),
            "dscratch1":int('7B3',16),
            "sstatus": int('100',16),
            "sedeleg": int('102',16),
            "sideleg": int('103',16),
            "sie": int('104',16),
            "stvec": int('105',16),
            "scounteren": int('106',16),
            "sscratch": int('140',16),
            "sepc": int('141',16),
            "scause": int('142',16),
            "stval": int('143',16),
            "sip": int('144',16),
            "satp": int('180',16),
            "vxsat": int('009',16),
            "fflags":int('1',16), 
            "frm":int('2',16),
            "fcsr":int('3',16)
        }
        for i in range(16):
            self.csr_regs["pmpaddr"+str(i)] = int('3B0',16)+i
        for i in range(3,32):
            self.csr_regs["mhpmcounter"+str(i)] = int('B03',16) + (i-3)
            self.csr_regs["mhpmcounter"+str(i)+"h"] = int('B83',16) + (i-3)
            self.csr_regs["mhpmevent"+str(i)] = int('323',16) + (i-3)

    def __setitem__ (self,key,value):
        if(isinstance(key, str)):
            self.csr[self.csr_regs[key]] = value
        else:
            self.csr[key] = value

    def __iter__(self):
        for entry in self.csr_regs.keys():
            yield (entry,self.csr_regs[entry],self.csr[self.csr_regs[entry]])

    def __len__(self):
        return len(self.csr)

    def __delitem__(self,key):
        pass

    def __getitem__ (self,key):
        if(isinstance(key, str)):
            return self.csr[self.csr_regs[key]]
        else:
            return self.csr[key]

class archState:
    '''
    Defines the architectural state of the RISC-V device.
    '''

    def __init__ (self, xlen, flen):
        '''
        Class constructor

        :param xlen: max XLEN value of the RISC-V device
        :param flen: max FLEN value of the RISC-V device

        :type xlen: int
        :type flen: int

        Currently defines the integer and floating point register files the
        width of which is defined by the xlen and flen parameters. These are
        implemented as an array holding the hexadecimal representations of the
        values as string.

        The program counter is also defined as an int.

        '''

        if xlen == 32:
            self.x_rf = ['00000000']*32
        else:
            self.x_rf = ['0000000000000000']*32

        if flen == 16:
            self.f_rf = ['0000']*32
            self.fcsr = 0
        elif flen == 32:
            self.f_rf = ['00000000']*32
        else:
            self.f_rf = ['0000000000000000']*32
        self.pc = 0
        self.flen = flen
class statistics:
    '''
    Class for holding statistics used for Data propagation report
    '''

    def __init__(self, xlen, flen):
        '''
        This class maintains a collection of arrays which are useful in
        calculating the following set of statistics:

        - STAT1 : Number of instructions that hit unique coverpoints and update the signature.
        - STAT2 : Number of instructions that hit covepoints which are not unique but still update the signature
        - STAT3 : Number of instructions that hit a unique coverpoint but do not update signature
        - STAT4 : Number of multiple signature updates for the same coverpoint
        - STAT5 : Number of times the signature was overwritten
        '''


        self.stat1 = []
        self.stat2 = []
        self.stat3 = []
        self.stat4 = []
        self.stat5 = []
        self.code_seq = []
        self.ucode_seq = []
        self.covpt = []
        self.ucovpt = []
        self.cov_pt_sig = []
        self.last_meta = []

def define_sem(flen, rsval, postfix, local_dict):
    '''
    This function expands the rsval and defining the respective sign, exponent and mantissa correspondence

    :param flen: Floating point length
    :param rsval: base rs value used to expand it's respective sign, exponent and mantissa
    :postfix: Register number that is part of the instruction
    :local_dict: Holding the copy of all the local variables from the function calling this function
    :return: The dictionary of variables with it's values
    '''
    if flen == 16:
        e_sz = 5
        m_sz = 10
    elif flen == 32:
        e_sz = 8
        m_sz = 23
    else:
        e_sz = 11
        m_sz = 52
    bin_val = bin(int('1'+rsval[2:],16))[3:]
    local_dict['fs'+postfix[2]] = int(bin_val[0])
    exp = bin_val[1:e_sz+1]
    man = bin_val[e_sz+1:]
    if flen == 16:
        feh = '1000'
        fmh = '100'
    elif flen == 32:
        feh = '1'
        fmh = '10'
    else:
        feh = '10'
        fmh = '1'
    local_dict['fe'+postfix[2]] = int(hex(int(feh+exp,2))[3:],16)
    local_dict['fm'+postfix[2]] = int(hex(int(fmh+man,2))[3:],16)

def pretty_print_yaml(yaml):
    res = ''''''
    for line in ruamel.yaml.round_trip_dump(yaml, indent=5, block_seq_indent=3).splitlines(True):
        res += line
    return res

def pretty_print_regfile(regfile):
    res = ""
    for index in range(0, 32, 4):
        print('x'+str(index) +   ' : ' + regfile[index] + '\t' +\
              'x'+str(index+1) + ' : ' + regfile[index+1] + '\t' + \
              'x'+str(index+2) + ' : ' + regfile[index+2] + '\t' + \
              'x'+str(index+3) + ' : ' + regfile[index+3] + '\t' )
    print('\n\n')

def gen_report(cgf, detailed):
    '''
    Function to convert a CGF to a string report. A detailed report includes the individual coverpoints and the corresponding values of the same

    :param cgf: an input CGF dictionary
    :param detailed: boolean value indicating a detailed report must be generated.

    :type cgf: dict
    :type detailed: bool

    :return: string holding the final report
    '''
    temp = cgf.copy()
    for cov_labels, value in cgf.items():
        if cov_labels != 'datasets':
            total_uncovered = 0
            total_categories = 0
            for categories in value:
                if categories not in ['cond','config','ignore']:
                    for coverpoints, coverage in value[categories].items():
                        if coverage == 0:
                            total_uncovered += 1
                    total_categories += len(value[categories])
            for categories in value:
                if categories not in ['cond','config','ignore']:
                    uncovered = 0
                    for coverpoints, coverage in value[categories].items():
                        if coverage == 0:
                            uncovered += 1
                    percentage_covered = str((len(value[categories]) - uncovered)/len(value[categories]))
                    node_level_str =  '  ' + categories + ':\n'
                    node_level_str += '    coverage: ' + \
                            str(len(value[categories]) - uncovered) + \
                            '/' + str(len(value[categories]))
                    temp[cov_labels][categories]['coverage'] = '{0}/{1}'.format(\
                        str(len(value[categories]) - uncovered),\
                        str(len(value[categories])))
            temp[cov_labels]['total_coverage'] = '{0}/{1}'.format(\
                    str(total_categories-total_uncovered),\
                    str(total_categories))
    return dict(temp)

def merge_files(files,i,k):
    '''
    Merges files from i to n where n is len(files) or i+k

    Arguments:

    files: List of dictionaries to be merged
    i : beginning index to merge files on a given core
    k : number of files to be merged

    '''

    temp = files[i]
    n = min(len(files),i+k)
    for logs_cov in files[i+1:n]:
        for cov_labels, value in logs_cov.items():
            if cov_labels not in temp:
                temp[cov_labels] = value
                continue
            for categories in value:
                if categories not in ['cond','config','ignore','total_coverage','coverage']:
                    if categories not in temp[cov_labels]:
                        temp[cov_labels][categories] = value[categories]
                        continue
                    for coverpoints, coverage in value[categories].items():
                        if coverpoints not in temp[cov_labels][categories]:
                            temp[cov_labels][categories][coverpoints] = coverage
                        else:
                            temp[cov_labels][categories][coverpoints] += coverage
    return temp

def merge_fn(files, cgf, p):

    '''
    Each core is assigned ceil(n/k) processes where n is len(files)
    '''


    pool_work = mp.Pool(processes = p)
    while(len(files)>1):
        n = len(files)
        max_process = math.ceil(n/p)
        if(max_process==1):
            max_process = 2
        files = pool_work.starmap_async(merge_files,[(files,i,max_process) for i in range(0,n,max_process)])
        files = files.get()
    pool_work.close()
    pool_work.join()

    return files[0]


def merge_coverage(inp_files, cgf, detailed, xlen, p=1):
    '''
    This function merges values of multiple CGF files and return a single cgf
    file. This can be treated analogous to how coverage files are merged
    traditionally.

    :param inp_files: an array of input CGF file names which need to be merged.
    :param cgf: a cgf against which coverpoints need to be checked for.
    :param detailed: a boolean value indicating if a detailed report needs to be generated
    :param xlen: XLEN of the trace
    :param p: Number of worker processes (>=1)

    :type inp_files: [str]
    :type cgf: dict
    :type detailed: bool
    :type xlen: int
    :type p: int

    :return: a string contain the final report of the merge.
    '''
    files = []
    for logs in inp_files:
        files.append(utils.load_yaml_file(logs))

    temp = merge_fn(files,cgf,p)
    for cov_labels, value in temp.items():
        for categories in value:
            if categories not in ['cond','config','ignore','total_coverage','coverage']:
                for coverpoints, coverage in value[categories].items():
                    if coverpoints in cgf[cov_labels][categories]:
                        cgf[cov_labels][categories][coverpoints] += coverage

    return gen_report(cgf, detailed)

def twos_complement(val,bits):
    if (val & (1 << (bits - 1))) != 0:
        val = val - (1 << bits)
    return val

def simd_val_unpack(val_comb, op_width, op_name, val, local_dict):
    '''
    This function unpacks `val` into its simd elements.

    :param val_comb: val_comb from the cgf dictionary
    :param op_name: name of the operand (rs1/rs2)
    :param val: operand value
    :param local_dict: locals() of the calling context

    '''
    simd_size = op_width
    simd_sgn = False
    for coverpoints in val_comb:
        if f"{op_name}_b0_val" in coverpoints:
            simd_size = 8
        if f"{op_name}_h0_val" in coverpoints:
            simd_size = 16
        if f"{op_name}_w0_val" in coverpoints:
            simd_size = 32
        if op_name in coverpoints:
            if any([s in coverpoints for s in ["<", "== -", "== (-"]]):
                simd_sgn = True

    fmt = {8: 'b', 16: 'h', 32: 'w', 64: 'd'}
    sz = fmt[simd_size]

    if simd_size > op_width:
        return

    elm_urange = 1<<simd_size
    elm_mask = elm_urange-1
    elm_msb_mask = (1<<(simd_size-1))
    for i in range(op_width//simd_size):
        elm_val = (val >> (i*simd_size)) & elm_mask
        if simd_sgn and (elm_val & elm_msb_mask) != 0:
            elm_val = elm_val - elm_urange
        local_dict[f"{op_name}_{sz}{i}_val"]=elm_val
    if simd_size == op_width:
        local_dict[f"{op_name}_val"]=elm_val

def compute_per_line(instr, cgf, xlen, addr_pairs,  sig_addrs):
    '''
    This function checks if the current instruction under scrutiny matches a
    particular coverpoint of interest. If so, it updates the coverpoints and
    return the same.

    :param instr: an instructionObject of the single instruction currently parsed
    :param cgf: a cgf against which coverpoints need to be checked for.
    :param xlen: Max xlen of the trace
    :param addr_pairs: pairs of start and end addresses for which the coverage needs to be updated

    :type instr: :class:`instructionObject`
    :type cgf: dict
    :type xlen: int
    :type addr_pairs: (int, int)
    '''
    global arch_state
    global csr_regfile
    global stats
    global result_count


    mnemonic = instr.mnemonic
    commitvalue = instr.reg_commit

    #-------------------ZFINX----------------------------
    #To check if Zfinx if part of the ISA
    has_Zfinx = 0
    if "Zfinx" in str(cgf[list(cgf.keys())[0]]['config']):
        has_Zfinx = 1
    #-----------------------------------------------------
    # assign default values to operands
    rs1 = 0
    rs2 = 0
    rs3 = 0
    rd  = 0
    rs1_type = 'x'
    rs2_type = 'x'
    rs3_type = 'f'
    rd_type = 'x'

    csr_addr = 0

    # create signed/unsigned conversion params
    if xlen == 32:
        unsgn_sz = '>I'
        sgn_sz = '>i'
    else:
        unsgn_sz = '>Q'
        sgn_sz = '>q'

    # if instruction is empty then return
    if instr is None:
        return cgf

    # check if instruction lies within the valid region of interest
    if addr_pairs:
        if any([instr.instr_addr >= saddr and instr.instr_addr < eaddr for saddr,eaddr in addr_pairs]):
            enable = True
        else:
            enable = False
    else:
        enable=True
    
    # capture the operands and their values from the regfile
    if instr.rs1 is not None:
        rs1 = instr.rs1[0]
        rs1_type = instr.rs1[1]
    if instr.rs2 is not None:
        rs2 = instr.rs2[0]
        rs2_type = instr.rs2[1]
    if instr.rs3 is not None:
        rs3 = instr.rs3[0]
        rs3_type = instr.rs3[1]

    if instr.rd is not None:
        rd = instr.rd[0]
        is_rd_valid = True
        rd_type = instr.rd[1]
    else:
        is_rd_valid = False

    if instr.imm is not None:
        imm_val = instr.imm
    if instr.shamt is not None:
        imm_val = instr.shamt
    if instr.zimm is not None:
        imm_val = instr.zimm

    try: 
        # special value conversion based on signed/unsigned operations
        if instr.instr_name in unsgn_rs1:
            rs1_val = struct.unpack(unsgn_sz, bytes.fromhex(arch_state.x_rf[rs1]))[0]
        elif instr.is_rvp:
            rs1_val = struct.unpack(unsgn_sz, bytes.fromhex(arch_state.x_rf[rs1]))[0]
            if instr.rs1_nregs == 2:
                rs1_hi_val = struct.unpack(unsgn_sz, bytes.fromhex(arch_state.x_rf[rs1+1]))[0]
                rs1_val = (rs1_hi_val << 32) | rs1_val
        elif rs1_type == 'x' and has_Zfinx == 0:
            if instr.instr_name in ["fmv.w.x","fcvt.s.l","fcvt.s.lu","fcvt.d.w","fcvt.d.wu", "fcvt.h.l", "fcvt.h.lu", "fmv.h.x"]:
                if arch_state.flen == 64:
                    if instr.instr_name in ["fcvt.d.w","fcvt.d.wu"] and int('0x' + ((arch_state.x_rf[rs1]).lower()[0]), 16) > 7 and xlen == 32:
                            rs1val = int('0x' + 'ffffffff' + (arch_state.x_rf[rs1]).lower(),16)
                    else:
                        rs1val = int('0x' + (arch_state.x_rf[rs1]).lower(),16)
                elif arch_state.flen == 32:
                    rs1val = int('0x' + (arch_state.x_rf[rs1][-8:]).lower(),16)
                else:
                    rs1val = int('0x' + (arch_state.x_rf[rs1][-4:]).lower(),16)
                rs1_val = twos_complement(rs1val,arch_state.flen) #To handle the signed integer values
            else:
                rs1_val = struct.unpack(sgn_sz, bytes.fromhex(arch_state.x_rf[rs1]))[0]
	#--------------------ZFINX-----------------------------------------------
        #For Zfinx extension, rs1_type will be 'x', use of arch_state.x_rf instead of arch_state.f_rf as in Float extension
        elif rs1_type == 'x' and has_Zfinx == 1:
            if instr.instr_name in ["fadd.s","fsub.s","fclass.s","fmul.s","fdiv.s","fsqrt.s","fmadd.s","fmsub.s","fnmadd.s","fnmsub.s","fmax.s","fmin.s","feq.s","flt.s","fle.s","fsgnj.s","fsgnjn.s","fsgnjx.s","fcvt.wu.s","fcvt.w.s","fcvt.lu.s","fcvt.l.s"]:
                rs1_val = '0x' + (arch_state.x_rf[rs1][-8:]).lower()
            elif instr.instr_name in ["fmv.w.x","fcvt.s.l","fcvt.s.lu","fcvt.d.w","fcvt.d.wu"]:
                if arch_state.flen == 64:
                    rs1val = int('0x' + (arch_state.x_rf[rs1]).lower(),16)
                elif arch_state.flen == 32:
                    rs1val = int('0x' + (arch_state.x_rf[rs1][-8:]).lower(),16)
                rs1_val = twos_complement(rs1val,arch_state.flen) #To handle the signed integer values
            else:
                rs1_val = struct.unpack(sgn_sz, bytes.fromhex(arch_state.x_rf[rs1]))[0]
    #-------------------------------------------------------------------------
        elif rs1_type == 'f':
            if instr.instr_name in ["fadd.s","fsub.s","fclass.s","fmul.s","fdiv.s","fsqrt.s","fmadd.s","fmsub.s","fnmadd.s","fnmsub.s","fmax.s","fmin.s","feq.s","flt.s","fle.s","fmv.x.w","fmv.w.x","fcvt.wu.s","fcvt.s.wu","fcvt.w.s","fcvt.s.w","fsgnj.s","fsgnjn.s","fsgnjx.s","fcvt.s.l", "fcvt.s.lu", "fcvt.h.s"]:
                rs1_val = '0x' + (arch_state.f_rf[rs1][-8:]).lower()
            elif instr.instr_name in ["fadd.h","fsub.h","fmul.h","fdiv.h","fsqrt.h","fmadd.h","fmsub.h","fnmadd.h","fnmsub.h","fmax.h","fmin.h","feq.h","flt.h","fle.h","fmv.x.h","fmv.h.x","fcvt.s.h","fcvt.h.s", "fcvt.h.d", "fcvt.d.h","fcvt.wu.h","fcvt.h.wu","fcvt.w.h","fcvt.h.w","fcvt.lu.h","fcvt.h.lu","fcvt.l.h","fcvt.h.l","fsgnj.h","fsgnjn.h","fsgnjx.h","fclass.h"]:
                rs1_val = '0x' + (arch_state.f_rf[rs1][-4:]).lower()
            else:
                rs1_val = '0x' + (arch_state.f_rf[rs1]).lower()
    except struct.error as err:
        logger.error("Structure exception thrown: Possible troubleshooting steps are below\n1. Check the buffersize using calcsize method\n2. Check the sixe of the variables being unpacked\n3. Now compare both and adjust accordingly")
        logger.error("Error Details are: \n", str(err))

    try:
        if instr.instr_name in unsgn_rs2:
            rs2_val = struct.unpack(unsgn_sz, bytes.fromhex(arch_state.x_rf[rs2]))[0]
        elif instr.is_rvp:
            rs2_val = struct.unpack(unsgn_sz, bytes.fromhex(arch_state.x_rf[rs2]))[0]
            if instr.rs2_nregs == 2:
                rs2_hi_val = struct.unpack(unsgn_sz, bytes.fromhex(arch_state.x_rf[rs2+1]))[0]
                rs2_val = (rs2_hi_val << 32) | rs2_val
        elif rs2_type == 'x' and has_Zfinx == 0:
            rs2_val = struct.unpack(sgn_sz, bytes.fromhex(arch_state.x_rf[rs2]))[0]

        #---------------------------ZFINX--------------------------------------------------------
        #For Zfinx extension, rs2_type will be 'x', use of arch_state.x_rf instead of arch_state.f_rf as in Float extension
        elif rs2_type == 'x' and has_Zfinx == 1:
            if instr.instr_name in ["fadd.s","fsub.s","fclass.s","fmul.s","fdiv.s","fmadd.s","fmsub.s","fnmadd.s","fnmsub.s","fmax.s","fmin.s","feq.s","flt.s","fle.s","fsgnj.s","fsgnjn.s","fsgnjx.s"]:
                rs2_val = '0x' + (arch_state.x_rf[rs2])[-8:].lower()
            elif instr.instr_name in ['addi', 'jalr']: 
                rs2_val = struct.unpack(sgn_sz, bytes.fromhex(arch_state.x_rf[rs2]))[0]
            elif instr.instr_name in ["fcvt.wu.s","fcvt.s.wu","fcvt.w.s","fcvt.s.w"]:
                rs2_val = '0x' + (arch_state.f_rf[rs2]).lower()
            else:
                rs2_val = struct.unpack(sgn_sz, bytes.fromhex(arch_state.x_rf[rs2]))[0]
        #----------------------------------------------------------------------------------------

        elif rs2_type == 'f':
            if instr.instr_name in ["fadd.s","fsub.s","fclass.s","fmul.s","fdiv.s","fmadd.s","fmsub.s","fnmadd.s","fnmsub.s","fmax.s","fmin.s","feq.s","flt.s","fle.s","fsgnj.s","fsgnjn.s","fsgnjx.s"]:
                rs2_val = '0x' + (arch_state.f_rf[rs2])[-8:].lower()
            elif instr.instr_name == "fsd" and xlen == 32:
                if int('0x' + ((arch_state.f_rf[rs2]).lower()[8]), 16) < 8:
                    rs2val = int('0x' + '00000000' + (arch_state.f_rf[rs2])[8:].lower(),16)
                else:
                    rs2val = int((arch_state.f_rf[rs2]).lower(),16)
                rs2_val = twos_complement(rs2val,arch_state.flen)
            elif instr.instr_name in ["fadd.h","fsub.h","fmul.h","fdiv.h","fmadd.h","fmsub.h","fnmadd.h","fnmsub.h","fmax.h","fmin.h","feq.h","flt.h","fle.h","fsgnj.h","fsgnjn.h","fsgnjx.h"]:
                rs2_val = '0x' + (arch_state.f_rf[rs2])[-4:].lower()
            else:
                rs2_val = '0x' + (arch_state.f_rf[rs2]).lower()
    except struct.error as err:
        logger.error("Structure exception thrown: Possible troubleshooting steps are below\n1. Check the buffersize using calcsize method\n2. Check the sixe of the variables being unpacked\n3. Now compare both and adjust accordingly")
        logger.error("Error Details are: \n", str(err))

    sig_update = False
    if instr.instr_name in ['sh','sb','sw','sd','c.sw','c.sd','c.swsp','c.sdsp'] and sig_addrs:
        store_address = rs1_val + imm_val
        for start, end in sig_addrs:
            if store_address >= start and store_address <= end:
                sig_update = True
                break        

    if sig_update: # writing result operands of last non-store instruction to the signature region
        result_count = result_count - 1
    else:
        result_count = instr.rd_nregs

    if instr.instr_name in ["fmadd.s","fmsub.s","fnmadd.s","fnmsub.s",\
        "fmadd.d","fmsub.d","fnmadd.d","fnmsub.d",\
        "fmadd.h","fmsub.h","fnmadd.h","fnmsub.h"]:
        rs3_val = '0x' + (arch_state.f_rf[rs3]).lower()
        #---------------------ZFINX------------------------
        #For Zfinx extension, rs2_type will be 'x', use of arch_state.x_rf instead of arch_state.f_rf as in Float extension
        if has_Zfinx == 1:
            rs3_val = '0x' + (arch_state.x_rf[rs3])[-8:].lower()
        #--------------------------------------------------
    if instr.instr_name in ['csrrwi']:
        csr_regfile.csr_regs["fcsr"] = instr.zimm

    #Having the rm value initiated before checking the conditions against instrucion names
    rm = instr.rm
    #Checking the rm  value if it is not none assigning it respectively from the respective csr in csr_regfile
    if rm is not None:
         if(rm==7):
              rm_val = csr_regfile.csr_regs["fcsr"]
         else:
              rm_val = rm
    else:
        rm_val = 0

    arch_state.pc = instr.instr_addr

    # the ea_align variable is used by the eval statements of the
    # coverpoints for conditional ops and memory ops
    if instr.instr_name in ['jal','bge','bgeu','blt','bltu','beq','bne']:
        ea_align = (instr.instr_addr+(imm_val<<1)) % 4

    if instr.instr_name == "jalr":
        ea_align = (rs1_val + imm_val) % 4

    if instr.instr_name in ['fsh','flh']:
        ea_align = (rs1_val + imm_val) % 2
    if instr.instr_name in ['sw','sh','sb','lw','lhu','lh','lb','lbu','lwu','flw','fsw']:
        ea_align = (rs1_val + imm_val) % 4
    if instr.instr_name in ['ld','sd','fld','fsd']:
        ea_align = (rs1_val + imm_val) % 8

    local_dict={}
    for i in csr_regfile.csr_regs:
        local_dict[i] = int(csr_regfile[i],16)

    local_dict['xlen'] = xlen
    if enable :
        for cov_labels,value in cgf.items():
            if cov_labels != 'datasets':
                if 'opcode' in value:
                    if instr.instr_name in value['opcode']:
                        if stats.code_seq:
                            logger.error('Found a coverpoint without sign Upd ' + str(stats.code_seq))
                            stats.stat3.append('\n'.join(stats.code_seq))
                            stats.code_seq = []
                            stats.covpt = []
                            stats.ucovpt = []
                            stats.ucode_seq = []

                        if value['opcode'][instr.instr_name] == 0:
                            stats.ucovpt.append('opcode : ' + instr.instr_name)
                        stats.covpt.append('opcode : ' + instr.instr_name)
                        value['opcode'][instr.instr_name] += 1
                        if 'rs1' in value and 'x'+str(rs1) in value['rs1']:
                            if value['rs1']['x'+str(rs1)] == 0:
                                stats.ucovpt.append('rs1 : ' + 'x'+str(rs1))
                            stats.covpt.append('rs1 : ' + 'x'+str(rs1))
                            value['rs1']['x'+str(rs1)] += 1
                        if 'rs2' in value and 'x'+str(rs2) in value['rs2']:
                            if value['rs2']['x'+str(rs2)] == 0:
                                stats.ucovpt.append('rs2 : ' + 'x'+str(rs2))
                            stats.covpt.append('rs2 : ' + 'x'+str(rs2))
                            value['rs2']['x'+str(rs2)] += 1
                        #----------------ZFINX------------------------------
                        if 'rs3' in value and 'x'+str(rs3) in value['rs3']:
                            if value['rs3']['x'+str(rs3)] == 0:
                                stats.ucovpt.append('rs3 : ' + 'x'+str(rs3))
                            stats.covpt.append('rs3 : ' + 'x'+str(rs3))
                            value['rs3']['x'+str(rs3)] += 1
                        #----------------------------------------------------
                        if 'rd' in value and is_rd_valid and 'x'+str(rd) in value['rd']:
                            if value['rd']['x'+str(rd)] == 0:
                                stats.ucovpt.append('rd : ' + 'x'+str(rd))
                            stats.covpt.append('rd : ' + 'x'+str(rd))
                            value['rd']['x'+str(rd)] += 1

                        if 'rs1' in value and 'f'+str(rs1) in value['rs1']:
                            if value['rs1']['f'+str(rs1)] == 0:
                                stats.ucovpt.append('rs1 : ' + 'f'+str(rs1))
                            stats.covpt.append('rs1 : ' + 'f'+str(rs1))
                            value['rs1']['f'+str(rs1)] += 1
                        if 'rs2' in value and 'f'+str(rs2) in value['rs2']:
                            if value['rs2']['f'+str(rs2)] == 0:
                                stats.ucovpt.append('rs2 : ' + 'f'+str(rs2))
                            stats.covpt.append('rs2 : ' + 'f'+str(rs2))
                            value['rs2']['f'+str(rs2)] += 1
                        if 'rs3' in value and 'f'+str(rs3) in value['rs3']:
                            if value['rs3']['f'+str(rs3)] == 0:
                                stats.ucovpt.append('rs3 : ' + 'f'+str(rs3))
                            stats.covpt.append('rs3 : ' + 'f'+str(rs3))
                            value['rs3']['f'+str(rs3)] += 1
                        if 'rd' in value and is_rd_valid and 'f'+str(rd) in value['rd']:
                            if value['rd']['f'+str(rd)] == 0:
                                stats.ucovpt.append('rd : ' + 'f'+str(rd))
                            stats.covpt.append('rd : ' + 'f'+str(rd))
                            value['rd']['f'+str(rd)] += 1

                        if 'op_comb' in value and len(value['op_comb']) != 0 :
                            lcls=locals().copy()
                            for coverpoints in value['op_comb']:
                                if eval(coverpoints):
                                    if cgf[cov_labels]['op_comb'][coverpoints] == 0:
                                        stats.ucovpt.append(str(coverpoints))
                                    stats.covpt.append(str(coverpoints))
                                    cgf[cov_labels]['op_comb'][coverpoints] += 1
                        if 'val_comb' in value and len(value['val_comb']) != 0:
                            if instr.instr_name in ["fadd.s","fsub.s","fmul.s","fdiv.s","fmax.s","fmin.s","feq.s","flt.s","fle.s","fsgnj.s","fsgnjn.s","fsgnjx.s",\
                                "fadd.d","fsub.d","fmul.d","fdiv.d","fmax.d","fmin.d","feq.d","flt.d","fle.d","fsgnj.d","fsgnjn.d","fsgnjx.d",\
                                'fadd.h',"fsub.h","fmul.h","fdiv.h","fmax.h","fmin.h","feq.h","flt.h","fle.h","fsgnj.h","fsgnjn.h","fsgnjx.h"]:
                                lcls=locals().copy()
                                #Function calls to expand the rs1 and rs2 values into it's respective floating point number (sign, exponent and mantissa) from the returned Hexa value
                                define_sem(int(arch_state.flen),rs1_val,"rs1",lcls)
                                define_sem(int(arch_state.flen),rs2_val,"rs2",lcls)
                                for coverpoints in value['val_comb']:
                                    if eval(coverpoints, lcls):
                                        if cgf[cov_labels]['val_comb'][coverpoints] == 0:
                                            stats.ucovpt.append(str(coverpoints))
                                        stats.covpt.append(str(coverpoints))
                                        cgf[cov_labels]['val_comb'][coverpoints] += 1
                            elif instr.instr_name in ["fsqrt.s","fcvt.wu.s","fcvt.w.s","fclass.s","fcvt.l.s","fcvt.lu.s","fmv.x.w",\
                                "fclass.d","fsqrt.d","fcvt.wu.d","fcvt.w.d","fcvt.d.s","fcvt.s.d","fmv.x.d","fcvt.l.d","fcvt.lu.d",\
                                "fclass.h","fsqrt.h","fcvt.wu.h","fcvt.w.h","fcvt.h.s","fcvt.s.h", "fcvt.h.d","fcvt.d.h","fmv.x.h","fcvt.l.h","fcvt.lu.h"]:
                                lcls=locals().copy()
                                #Function calls to expand the rs1 value into it's respective floating point number (sign, exponent and mantissa) from the returned Hexa value
                                define_sem(int(arch_state.flen),rs1_val,"rs1",lcls)
                                for coverpoints in value['val_comb']:
                                    if eval(coverpoints, lcls):
                                        if cgf[cov_labels]['val_comb'][coverpoints] == 0:
                                            stats.ucovpt.append(str(coverpoints))
                                        stats.covpt.append(str(coverpoints))
                                        cgf[cov_labels]['val_comb'][coverpoints] += 1
                            elif instr.instr_name in ["fmadd.s","fmsub.s","fnmadd.s","fnmsub.s",\
                                "fmadd.d","fmsub.d","fnmadd.d","fnmsub.d",\
                                "fmadd.h","fmsub.h","fnmadd.h","fnmsub.h"]:
                                lcls=locals().copy()
                                #Function calls to expand the rs1,rs2 and rs3 values into it's respective floating point number (sign, exponent and mantissa) from the returned Hexa value
                                define_sem(int(arch_state.flen),rs1_val,"rs1",lcls)
                                define_sem(int(arch_state.flen),rs2_val,"rs2",lcls)
                                define_sem(int(arch_state.flen),rs3_val,"rs3",lcls)
                                for coverpoints in value['val_comb']:
                                    if eval(coverpoints, lcls):
                                        if cgf[cov_labels]['val_comb'][coverpoints] == 0:
                                            stats.ucovpt.append(str(coverpoints))
                                        stats.covpt.append(str(coverpoints))
                                        cgf[cov_labels]['val_comb'][coverpoints] += 1
                            else:
                                lcls=locals().copy()
                                if instr.is_rvp and "rs1" in value:
                                    op_width = 64 if instr.rs1_nregs == 2 else xlen
                                    simd_val_unpack(value['val_comb'], op_width, "rs1", rs1_val, lcls)
                                if instr.is_rvp and "rs2" in value:
                                    op_width = 64 if instr.rs2_nregs == 2 else xlen
                                    simd_val_unpack(value['val_comb'], op_width, "rs2", rs2_val, lcls)
                                for coverpoints in value['val_comb']:
                                    if eval(coverpoints,globals(),lcls):
                                        if cgf[cov_labels]['val_comb'][coverpoints] == 0:
                                            stats.ucovpt.append(str(coverpoints))
                                        stats.covpt.append(str(coverpoints))
                                        cgf[cov_labels]['val_comb'][coverpoints] += 1
                        if 'abstract_comb' in value \
                                and len(value['abstract_comb']) != 0 :
                            for coverpoints in value['abstract_comb']:
                                if eval(coverpoints):
                                    if cgf[cov_labels]['abstract_comb'][coverpoints] == 0:
                                        stats.ucovpt.append(str(coverpoints))
                                    stats.covpt.append(str(coverpoints))
                                    cgf[cov_labels]['abstract_comb'][coverpoints] += 1

                        if 'csr_comb' in value and len(value['csr_comb']) != 0:
                            for coverpoints in value['csr_comb']:
                                if eval(coverpoints, {"__builtins__":None}, local_dict):
                                    if cgf[cov_labels]['csr_comb'][coverpoints] == 0:
                                        stats.ucovpt.append(str(coverpoints))
                                    stats.covpt.append(str(coverpoints))
                                    cgf[cov_labels]['csr_comb'][coverpoints] += 1
                elif 'opcode' not in value:
                    if 'csr_comb' in value and len(value['csr_comb']) != 0:
                        for coverpoints in value['csr_comb']:
                            if eval(coverpoints, {"__builtins__":None}, local_dict):
                                if cgf[cov_labels]['csr_comb'][coverpoints] == 0:
                                    stats.ucovpt.append(str(coverpoints))
                                stats.covpt.append(str(coverpoints))
                                cgf[cov_labels]['csr_comb'][coverpoints] += 1
        if stats.covpt:
            if mnemonic is not None :
                stats.code_seq.append('[' + str(hex(instr.instr_addr)) + ']:' + mnemonic)
            else:
                stats.code_seq.append('[' + str(hex(instr.instr_addr)) + ']:' + instr.instr_name)
        if stats.ucovpt:
            if mnemonic is not None :
                stats.ucode_seq.append('[' + str(hex(instr.instr_addr)) + ']:' + mnemonic)
            else:
                stats.ucode_seq.append('[' + str(hex(instr.instr_addr)) + ']:' + instr.instr_name)

    if instr.instr_name in ['sh','sb','sw','sd','c.sw','c.sd','c.swsp','c.sdsp'] and sig_addrs:
        store_address = rs1_val + imm_val
        store_val = '0x'+arch_state.x_rf[rs2]
        for start, end in sig_addrs:
            if store_address >= start and store_address <= end:
                logger.debug('Signature update : ' + str(hex(store_address)))
                stats.stat5.append((store_address, store_val, stats.ucovpt, stats.code_seq))
                stats.cov_pt_sig += stats.covpt
                if result_count <= 0:
                    if stats.ucovpt:
                        stats.stat1.append((store_address, store_val, stats.ucovpt, stats.ucode_seq))
                        stats.last_meta = [store_address, store_val, stats.ucovpt, stats.ucode_seq]
                        stats.ucovpt = []
                    elif stats.covpt:
                        _log = 'Op without unique coverpoint updates Signature\n'
                        _log += ' -- Code Sequence:\n'
                        for op in stats.code_seq:
                            _log += '      ' + op + '\n'
                        _log += ' -- Signature Address: {0} Data: {1}\n'.format(
                                str(hex(store_address)), store_val)
                        _log += ' -- Redundant Coverpoints hit by the op\n'
                        for c in stats.covpt:
                            _log += '      - ' + str(c) + '\n'
                        logger.warn(_log)
                        stats.stat2.append(_log + '\n\n')
                        stats.last_meta = [store_address, store_val, stats.covpt, stats.code_seq]
                    else:
                        if len(stats.last_meta):
                            _log = 'Last Coverpoint : ' + str(stats.last_meta[2]) + '\n'
                            _log += 'Last Code Sequence : \n\t-' + '\n\t-'.join(stats.last_meta[3]) + '\n'
                            _log +='Current Store : [{0}] : {1} -- Store: [{2}]:{3}\n'.format(\
                                str(hex(instr.instr_addr)), mnemonic,
                                str(hex(store_address)),
                                store_val)
                            logger.error(_log)
                            stats.stat4.append(_log + '\n\n')
                    stats.covpt = []
                    stats.code_seq = []
                    stats.ucode_seq = []

    if commitvalue is not None:
        if rd_type == 'x'and has_Zfinx==0:
            arch_state.x_rf[int(commitvalue[1])] =  str(commitvalue[2][2:])
        elif rd_type == 'x'and has_Zfinx==1:
            offset = len(commitvalue[2])-len(arch_state.x_rf[int(commitvalue[1])])
            arch_state.x_rf[int(commitvalue[1])] =  str(commitvalue[2][offset:])
        elif rd_type == 'f':
            offset = len(commitvalue[2])-len(arch_state.f_rf[int(commitvalue[1])])
            arch_state.f_rf[int(commitvalue[1])] =  str(commitvalue[2][offset:])
        else:
            logger.debug("Register type Not found")

    csr_commit = instr.csr_commit
    if csr_commit is not None:
        for commits in csr_commit:
            if(commits[0]=="CSR"):
                csr_regfile[commits[1]] = str(commits[2][2:])

    return cgf

def compute(trace_file, test_name, cgf, parser_name, decoder_name, detailed, xlen, flen, addr_pairs
        , dump, cov_labels, sig_addrs, window_size):
    '''Compute the Coverage'''

    global arch_state
    global csr_regfile
    global stats
    global cross_cover_queue
    global result_count

    temp = cgf.copy()
    if cov_labels:
        for groups in cgf:
            if groups not in cov_labels:
                del temp[groups]
        cgf = temp

    if dump is not None:
        dump_f = open(dump, 'w')
        dump_f.write(ruamel.yaml.round_trip_dump(cgf, indent=5, block_seq_indent=3))
        dump_f.close()
        sys.exit(0)

    #This flen value is being used in compute_per_line method to build the the  string, in-order to cross-veriy the coverpoints
    arch_state = archState(xlen,flen)
    csr_regfile = csr_registers(xlen)
    stats = statistics(xlen,flen)
    cross_cover_queue = []
    result_count = 0

    ## Get coverpoints from cgf
    obj_dict = {} ## (label,coverpoint): object
    for cov_labels,value in cgf.items():
        if cov_labels != 'datasets':
            if 'cross_comb' in value and len(value['cross_comb'])!=0:
                for coverpt in value['cross_comb'].keys():
                    if(isinstance(coverpt,str)):
                        new_obj = cross(cov_labels,coverpt)
                        obj_dict[(cov_labels,coverpt)] = new_obj


    parser_pm = pluggy.PluginManager("parser")
    parser_pm.add_hookspecs(ParserSpec)
    try:
        parserfile = importlib.import_module(parser_name)
    except ImportError as e:
        logger.error('Error while importing Parser!')
        logger.error(e)
        raise SystemExit
    parserclass = getattr(parserfile, parser_name)
    parser_pm.register(parserclass())
    parser = parser_pm.hook
    parser.setup(trace=trace_file,arch="rv"+str(xlen))

    decoder_pm = pluggy.PluginManager("decoder")
    decoder_pm.add_hookspecs(DecoderSpec)
    try:
        instructionObjectfile = importlib.import_module(decoder_name)
    except ImportError as e:
        logger.error('Error while importing Decoder!')
        logger.error(e)
        raise SystemExit
    decoderclass = getattr(instructionObjectfile, "disassembler")
    decoder_pm.register(decoderclass())
    decoder = decoder_pm.hook
    decoder.setup(arch="rv"+str(xlen))

    iterator = iter(parser.__iter__()[0])
    rcgf = cgf
    for instrObj_temp in iterator:
        
        instr = instrObj_temp.instr
        if instr is None:
            continue
        instrObj = (decoder.decode(instrObj_temp = instrObj_temp))[0]
        logger.debug(instrObj)
        cross_cover_queue.append(instrObj)
        if(len(cross_cover_queue)>=window_size):
            for (label,coverpt) in obj_dict.keys():
                obj_dict[(label,coverpt)].process(cross_cover_queue, window_size,addr_pairs)
            cross_cover_queue.pop(0)
        #-----------------------------ZFINX------------------------------------
        #has_Zfinx captures the presence of ZFINX in the ISA
        has_Zfinx = 0
        if "_Zfinx" in str(rcgf[list(rcgf.keys())[0]]['config']):
            has_Zfinx = 1
        #Internal decoder fills the instrObj.rs1/rs2/rs3/reg_commit values with 'f' however for Zfinx 'x' has to be used.
        #Below code is for modifying the objects with 'x' if Zfinx is in ISA. 
        if has_Zfinx==1 and any(float_instr in instrObj.mnemonic for float_instr in ["fadd.s","fsub.s","fclass.s","fmul.s","fdiv.s","fsqrt.s","fmadd.s","fmsub.s","fnmadd.s","fnmsub.s","fmax.s","fmin.s","feq.s","flt.s","fle.s","fmv.x.w","fmv.w.x","fcvt.wu.s","fcvt.s.wu","fcvt.w.s","fcvt.s.w","fsgnj.s","fsgnjn.s","fsgnjx.s","fcvt.s.l", "fcvt.s.lu", "fmadd.s","fcvt.l.s","fcvt.lu.s" ]):
            if instrObj.reg_commit is not None:
                instrObj.reg_commit = ('x', instrObj.reg_commit[1], instrObj.reg_commit[2])
            instrObj.rs1 = (instrObj.rs1[0],'x')
            if instrObj.rs2 is not None:
                instrObj.rs2 = (instrObj.rs2[0],'x')
            if instrObj.rs3 is not None:
                instrObj.rs3 = (instrObj.rs3[0],'x')
            instrObj.rd = (instrObj.rd[0],'x')

        #-----------------------------------------------------------------------
        rcgf = compute_per_line(instrObj, rcgf, xlen, addr_pairs, sig_addrs)

    ## Check for cross coverage for end instructions
    ## All metric is stored in objects of obj_dict
    while(len(cross_cover_queue)>1):
        for label,coverpt in obj_dict.keys():
            obj_dict[(label,coverpt)].process(cross_cover_queue, window_size,addr_pairs)
        cross_cover_queue.pop(0)

    for label,coverpt in obj_dict.keys():
        metric = obj_dict[(label,coverpt)].get_metric()
        if(metric!=0):
            rcgf[label]['cross_comb'][coverpt] = metric

    rpt_str = gen_report(rcgf, detailed)
    logger.info('Writing out updated cgf : ' + test_name + '.cgf')
    dump_file = open(test_name+'.cgf', 'w')
    dump_file.write(ruamel.yaml.round_trip_dump(rcgf, indent=5, block_seq_indent=3))
    dump_file.close()


    if sig_addrs:
        logger.info('Creating Data Propagation Report : ' + test_name + '.md')
        writer = pytablewriter.MarkdownTableWriter()
        writer.headers = ["s.no","signature", "coverpoints", "code"]
        total_categories = 0
        for cov_labels, value in cgf.items():
            if cov_labels != 'datasets':
              #  rpt_str += cov_labels + ':\n'
                total_uncovered = 0
                for categories in value:
                    if categories not in ['cond','config','ignore', 'total_coverage', 'coverage']:
                        for coverpoints, coverage in value[categories].items():
                            if coverage == 0:
                                total_uncovered += 1
                        total_categories += len(value[categories])

        addr_pairs_hex = []
        for x in addr_pairs:
            _x = (hex(x[0]), hex(x[1]))
            addr_pairs_hex.append(_x)
        sig_addrs_hex = []
        for x in sig_addrs:
            if xlen == 64:
                _x = (hex(x[0]), hex(x[1]), str(int((x[1]-x[0])/8)) + ' dwords')
            else:
                _x = (hex(x[0]), hex(x[1]), str(int((x[1]-x[0])/4)) + ' words')
            sig_addrs_hex.append(_x)

        cov_set = set()
        count = 1
        stat5_log = []
        for addr,val,cover,code in stats.stat1:
            sig = ('[{0}]<br>{1}'.format(str(hex(addr)), str(val)))
            cov = ''
            for c in cover:
                cov += '- ' + str(c) + '<br>\n'
                cov_set.add(c)
            cod = ''
            for i in code:
                cod += str(i) + '<br>\n'

            row = [count, sig, cov, cod]
            writer.value_matrix.append(row)
            count += 1
        f =open(test_name+'.md','w')
        if xlen == 64:
            sig_count = 2*len(stats.stat5)
        else:
            sig_count = len(stats.stat5)

        stat2_log = ''
        for _l in stats.stat2:
            stat2_log += _l + '\n\n'

        stat4_log = ''
        for _l in stats.stat4:
            stat4_log += _l + '\n\n'

        stat3_log = ''
        for _l in stats.stat3:
            stat3_log += _l + '\n\n'

        stat5_log = ''
        sig_set = set()
        overwrites = 0
        for addr, val, cover, code in stats.stat5:
            if addr in sig_set:
                stat5_log += ('[{0}]<br>{1}'.format(str(hex(addr)), str(val)))
                stat5_log += code + '\n\n'
                overwrites += 1
                sig_set.add(addr)
                logger.error('Found overwrite in Signature at Addr : ' +
                        str(addr))

        f.write(dpr_template.format(str(xlen),
            str(addr_pairs_hex),
            str(sig_addrs_hex),
            str(cov_labels),
            test_name,
            total_categories,
            len(stats.stat5),
            len(set(stats.cov_pt_sig)),
            len(stats.stat1),
            len(stats.stat2),
            len(stats.stat3),
            len(stats.stat4),
            len(stat5_log),
            stat2_log,
            stat3_log,
            stat4_log,
            stat5_log))
        f.write(writer.dumps())
        f.close()

    return rpt_str

