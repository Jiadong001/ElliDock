#!/usr/bin/python
# -*- coding:utf-8 -*-
from collections import defaultdict
import re
import json
from argparse import ArgumentParser
import os
import shutil
from Bio import PDB
from tqdm import tqdm
import sys
sys.path.append('..')
from utils.geometry import rand_rotation_matrix
import numpy as np


def parse():
    parser = ArgumentParser(description='split train / valid / test')
    parser.add_argument('--data', type=str, required=True, help='Path to the data file')
    parser.add_argument('--out_dir', type=str, default=None,
                        help='Directory to save results. Default the same as input data.')
    parser.add_argument('--valid_ratio', type=float, default=0.1,
                        help='Ratio of validation set')
    parser.add_argument('--test_ratio', type=float, default=0.1,
                        help='Ratio of test set')
    parser.add_argument('--cdr', type=str,
                        choices=[f'cdrh{i}' for i in range(1, 4)] + [f'cdrl{i}' for i in range(1, 4)],
                        default=None,
                        help='Cluster according to which cdr, None for using the entire sequence of antibody')
    parser.add_argument('--filter', type=str, default='1*1', help='Filter out complex with heavy / light / antigen.' + \
                                                                  'The code refers to heavy / light / antigen sequentially. 1 for has, 0 for not has, * for either.' + \
                                                                  'e.g default 1*1 means has heavy chain and antigen, either has light chain or not.')
    parser.add_argument('--k_fold', type=int, default=-1, help='K fold dataset. -1 for not do k-fold.' + \
                                                               'Note that if this is enabled, the test/valid ratio will be automatically calculated.')
    parser.add_argument('--seed', type=int, default=2022, help='seed')
    parser.add_argument('--rabd', type=str, default=None, help='Path to rabd json file. If this is enabled, ' + \
                                                               'RAbD complexes will be used as test set and complexes from data will be used as train/valid.' + \
                                                               'Note that complexes sharing clusters with RAbD will be dropped.' + \
                                                               'K fold will also be turned off.')
    return parser.parse_args()


def load_file(fpath):
    with open(fpath, 'r') as fin:
        lines = fin.read().strip().split('\n')
    items = [json.loads(s) for s in lines]
    return items


def save_file(lines, fpath):
    with open(fpath, 'w') as fout:
        fout.writelines(lines)


def exec_mmseq(cmd):
    r = os.popen(cmd)
    text = r.read()
    r.close()
    return text


def filter_flag(items, code):
    res = []
    for item in items:
        satisfy = True
        for permit, key in zip(code, ['heavy_chain', 'light_chain', 'antigen_chains']):
            if permit == '*':
                continue
            satisfy = len(item[key]) == 0 if permit == '0' else len(item[key]) > 0
            if not satisfy:
                break
        res.append(satisfy)
    return res


def gen_test_set(test_path):
    par_dir = os.path.abspath(os.path.dirname(os.getcwd()))
    dataset_dir = os.path.join(par_dir, 'test_sets_pdb', 'sabdab_test_random_transformed')
    complex_dir = os.path.join(dataset_dir, 'complexes')
    random_dir = os.path.join(dataset_dir, 'random_transformed')
    os.makedirs(dataset_dir, exist_ok=True)
    os.makedirs(complex_dir, exist_ok=True)
    os.makedirs(random_dir, exist_ok=True)
    with open(test_path, 'r') as fin:
        lines = fin.read().strip().split('\n')
    pdbs = []
    for line in tqdm(lines):
        item = json.loads(line)
        pdb = item['pdb']
        pdbs.append(pdb)
        ab_complex_name, ag_complex_name = f'{pdb}_r_b_COMPLEX.pdb', f'{pdb}_l_b_COMPLEX.pdb'
        ab_random_name, ag_random_name = f'{pdb}_r_b.pdb', f'{pdb}_l_b.pdb'
        hchain, lchain, agchains = item['heavy_chain'], item['light_chain'], item['antigen_chains']
        parser = PDB.PDBParser()
        structure = parser.get_structure(pdb, item['pdb_data_path'])
        ab_writer = PDB.PDBIO()
        ag_writer = PDB.PDBIO()
        ab_model = PDB.Model.Model(f'{pdb}_r')
        ag_model = PDB.Model.Model(f'{pdb}_l')

        for model in structure:
            for chain in model:
                if chain.id in [hchain, lchain]:
                    ab_model.add(chain)
                elif chain.id in agchains:
                    ag_model.add(chain)

        ab_writer.set_structure(ab_model)
        ab_complex_path = os.path.join(complex_dir, ab_complex_name)
        ab_writer.save(ab_complex_path)

        ag_writer.set_structure(ag_model)
        ag_complex_path = os.path.join(complex_dir, ag_complex_name)
        ag_writer.save(ag_complex_path)

        q = rand_rotation_matrix().numpy()
        t = np.random.rand(3) * 15.0        # std ~ 15.0

        ab_structure = parser.get_structure(pdb, ab_complex_path)
        for model in ab_structure:
            for chain in model:
                for residue in chain:
                    for atom in residue:
                        atom_coord = atom.get_coord()
                        atom.set_coord(atom_coord @ q + t)
        io = PDB.PDBIO()
        io.set_structure(ab_structure)
        io.save(os.path.join(random_dir, ab_random_name))

        q = rand_rotation_matrix().numpy()
        t = np.random.rand(3) * 15.0  # std ~ 15.0

        ag_structure = parser.get_structure(pdb, ag_complex_path)
        for model in ag_structure:
            for chain in model:
                for residue in chain:
                    for atom in residue:
                        atom_coord = atom.get_coord()
                        atom.set_coord(atom_coord @ q + t)
        io = PDB.PDBIO()
        io.set_structure(ag_structure)
        io.save(os.path.join(random_dir, ag_random_name))


    with open(os.path.join(dataset_dir, 'test.txt'), 'w') as fp:
        for pdb in pdbs:
            fp.write(f'{pdb}\n')


def main(args):
    np.random.seed(args.seed)

    items = load_file(args.data)
    flags = filter_flag(items, args.filter)
    items = [items[i] for i in range(len(flags)) if flags[i]]
    print(f'Valid entries after filtering with {args.filter}: {len(items)}')

    if args.rabd is not None:
        rabd = load_file(args.rabd)
        flags = filter_flag(rabd, args.filter)
        rabd = [rabd[i] for i in range(len(flags)) if flags[i]]
        print(f'RAbD enabled as test set. Valid entries: {len(rabd)}')
        is_rabd = [False for _ in items]
        items.extend(rabd)
        is_rabd.extend([True for _ in rabd])

    # transfer to fasta format
    tmp_dir = './tmp'
    if not os.path.exists(tmp_dir):
        os.makedirs(tmp_dir)
    else:
        raise ValueError(f'Working directory {tmp_dir} exists!')
    fasta = os.path.join(tmp_dir, 'seq.fasta')
    with open(fasta, 'w') as fout:
        for item in items:
            pdb = item['pdb']
            if args.cdr is None:
                seq = item['hchain_seq'] + item['lchain_seq']
            else:
                seq = item[f'{args.cdr}_seq']
            fout.write(f'>{pdb}\n{seq}\n')
    db = os.path.join(tmp_dir, 'DB')
    cmd = f'mmseqs createdb {fasta} {db}'
    exec_mmseq(cmd)
    db_clustered = os.path.join(tmp_dir, 'DB_clu')
    cmd = f'mmseqs cluster {db} {db_clustered} {tmp_dir} --min-seq-id 0.8'  # similarity > 0.8 in the same cluster
    res = exec_mmseq(cmd)
    num_clusters = re.findall(r'Number of clusters: (\d+)', res)
    if len(num_clusters):
        print(f'Number of clusters: {num_clusters[0]}')
    else:
        raise ValueError('cluster failed!')
    tsv = os.path.join(tmp_dir, 'DB_clu.tsv')
    cmd = f'mmseqs createtsv {db} {db} {db_clustered} {tsv}'
    exec_mmseq(cmd)

    # read tsv of class \t pdb
    with open(tsv, 'r') as fin:
        entries = fin.read().strip().split('\n')
    pdb2clu, clu2idx = {}, defaultdict(list)
    for entry in entries:
        cluster, pdb = entry.strip().split('\t')
        pdb2clu[pdb] = cluster
    for i, item in enumerate(items):
        pdb = item['pdb']
        cluster = pdb2clu[pdb]
        clu2idx[cluster].append(i)

    clu_cnt = [len(clu2idx[clu]) for clu in clu2idx]
    print(f'cluster number: {len(clu2idx)}, member number ' +
          f'mean: {np.mean(clu_cnt)}, min: {min(clu_cnt)}, ' +
          f'max: {max(clu_cnt)}')

    if args.out_dir is None:
        if args.rabd is None:
            data_dir = os.path.split(args.data)[0]
        else:
            data_dir = os.path.split(args.rabd)[0]
    else:
        data_dir = args.out_dir
        if not os.path.exists(data_dir):
            os.makedirs(data_dir)

    fnames = ['train', 'valid', 'test']
    if args.rabd is not None:
        rabd_clusters, other_clusters = [], []
        for c in clu2idx:
            in_test = False
            for i in clu2idx[c]:
                if is_rabd[i]:
                    in_test = True
                    break
            if in_test:
                rabd_clusters.append(c)
            else:
                other_clusters.append(c)
        np.random.shuffle(other_clusters)
        valid_len = int(len(other_clusters) * args.valid_ratio)
        valid_clusters = other_clusters[-valid_len:]
        train_clusters = other_clusters[:-valid_len]
        for f, clusters in zip(fnames, [train_clusters, valid_clusters, rabd_clusters]):
            is_test = f == 'test'
            f = os.path.join(data_dir, f + '.json')
            fout, cnt = open(f, 'w'), 0
            for c in clusters:
                for i in clu2idx[c]:
                    if is_test and not is_rabd[i]:
                        continue
                    items[i]['cluster'] = c
                    fout.write(json.dumps(items[i]) + '\n')
                    cnt += 1
            fout.close()
            print(f'Save {len(clusters)} clusters, {cnt} entries to {f}')
    else:
        clusters = list(clu2idx.keys())
        np.random.shuffle(clusters)
        if args.k_fold == -1:  # not do k-fold
            valid_len, test_len = len(clu2idx) * args.valid_ratio, len(clu2idx) * args.test_ratio
            valid_len, test_len = int(valid_len), int(test_len)
            lengths = [len(clu2idx) - valid_len - test_len, valid_len, test_len]

            start = 0
            for n, l in zip(fnames, lengths):
                assert 0 <= l and l < len(clusters)
                if l == 0:
                    continue
                cnt = 0
                end = start + l
                n = os.path.join(data_dir, n + '.json')
                fout = open(n, 'w')
                for c in clusters[start:end]:
                    for i in clu2idx[c]:
                        items[i]['cluster'] = c
                        fout.write(json.dumps(items[i]) + '\n')
                        cnt += 1
                fout.close()
                start = end
                print(f'Save {l} clusters, {cnt} entries to {n}')
        else:
            print(f'{args.k_fold}-fold data split')
            valid_len = test_len = int(len(clu2idx) * 1.0 / args.k_fold)
            left_ids = [left_id for left_id in range(args.k_fold * test_len, len(clu2idx))]
            for k in range(args.k_fold):
                fold_dir = os.path.join(data_dir, f'fold_{k}')
                if not os.path.exists(fold_dir):
                    os.makedirs(fold_dir)
                test_idx, train_idx = [], []
                test_start = k * test_len
                test_end = test_start + test_len
                for i, c in enumerate(clusters):
                    if i in left_ids:
                        if i % args.k_fold == k:
                            test_idx.append(i)
                    elif i >= test_start and i < test_end:
                        test_idx.append(i)
                    else:
                        train_idx.append(i)
                valid_idx = train_idx[-valid_len:]
                train_idx = train_idx[:-valid_len]
                for n, idxs in zip(fnames, [train_idx, valid_idx, test_idx]):
                    cnt = 0
                    n = os.path.join(fold_dir, n + '.json')
                    fout = open(n, 'w')
                    for idx in idxs:
                        c = clusters[idx]
                        for i in clu2idx[c]:
                            items[i]['cluster'] = c
                            fout.write(json.dumps(items[i]) + '\n')
                            cnt += 1
                    fout.close()
                    print(f'Save {len(idxs)} clusters, {cnt} entries to {n}')

    shutil.rmtree(tmp_dir)
    gen_test_set(os.path.join(data_dir, 'test.json'))


if __name__ == '__main__':
    main(parse())
